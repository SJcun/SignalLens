"""Claim 级反馈、高级纠错与 Evaluate Delta 输入的测试。"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

TEST_DB = Path(__file__).with_name("test.db")
TEST_BOOTSTRAP = Path(__file__).with_name("initial-admin-password.txt")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SIGNALLENS_BOOTSTRAP_PASSWORD_FILE"] = str(TEST_BOOTSTRAP)

from fastapi.testclient import TestClient
from sqlalchemy import select

import signallens.main as main_module
import signallens.worker as worker_module
from signallens.analysis.compare import CognitiveCompare, CompareRelation
from signallens.analysis.prompts import evaluate_input
from signallens.analysis.schemas import (
    AnalyzeContent,
    CurrentUserState,
    EvaluateForUser,
    TriageContent,
    UserProfile,
)
from signallens.database import SessionLocal, create_schema, engine
from signallens.memory import MemoryMatchJudgment, create_memory
from signallens.models import (
    Analysis,
    AnalysisJob,
    ClaimFeedbackEvent,
    Content,
    ContentClaim,
)
from signallens.worker import process_next_job


class FullProvider:
    """支持三阶段 + Compare + Memory Match 的确定性 Provider。"""

    model = "full-test-model"

    def __init__(self, relations_factory=None, match_decision="different"):
        self.relations_factory = relations_factory
        self.match_decision = match_decision

    def complete(self, *, system_prompt, user_prompt, output_model):
        """按输出模型类型返回最小有效结果。"""

        if output_model is TriageContent:
            return TriageContent(
                relevance="low",
                intrinsic_signal="low",
                novelty_signal="unknown",
                exploration_value="low",
                discovery_type="profile_match",
                decision="ignore",
                reason="测试模型的快速判断",
                why_outside_profile=None,
            )
        if output_model is AnalyzeContent:
            return AnalyzeContent(
                one_sentence_summary="文章介绍了一个值得验证的新方法。",
                summary="这是一段用于回归测试的内容分析。",
                content_profile={
                    "topics": ["测试"],
                    "content_type": "技术文章",
                    "difficulty": "introductory",
                },
                content_map=[],
                key_points=["关键点一"],
                claims=[
                    {
                        "claim": "方法 X 在条件 A 下有效",
                        "claim_type": "fact",
                        "claim_role": "core",
                        "change_signal": "none",
                        "section_ref": None,
                        "evidence": ["原文实验"],
                        "verification": "supported_in_content",
                        "topics": ["Agent Memory"],
                        "entities": ["MCP"],
                    },
                    {
                        "claim": "细节：参数取值为 3",
                        "claim_type": "fact",
                        "claim_role": "detail",
                        "change_signal": "none",
                        "section_ref": None,
                        "evidence": ["原文例子"],
                        "verification": "unverified",
                        "topics": [],
                        "entities": [],
                    },
                ],
                thesis=None,
                supporting_evidence=[],
                counterarguments=[],
                author_stance=None,
                limitations=[],
                unresolved_questions=[],
                unverified_claims=[],
            )
        if output_model is EvaluateForUser:
            return EvaluateForUser(
                relevance="medium",
                knowledge_overlap="low",
                known_or_redundant=False,
                novel_information=["关键点一"],
                exploration_value="medium",
                perspective_diversity="medium",
                discovery_type="adjacent",
                recommendation="selective_read",
                recommendation_reason="包含一项可快速验证的新信息",
                why_outside_profile=None,
                reading_plan=[
                    {"section": "关键点一", "action": "read", "reason": "验证新方法"}
                ],
            )
        if output_model is CognitiveCompare:
            assert self.relations_factory is not None
            return CognitiveCompare(relations=self.relations_factory(user_prompt))
        if output_model is MemoryMatchJudgment:
            return MemoryMatchJudgment(
                decision=self.match_decision,
                confidence="high" if self.match_decision != "uncertain" else "low",
                reason="测试判断",
            )
        raise AssertionError(f"未处理的输出模型：{output_model}")


def setup_module() -> None:
    """每个测试文件只建一次共享数据库结构。"""

    create_schema()


def teardown_module() -> None:
    """显式释放 SQLite 文件句柄，再删除临时数据库和凭据文件。"""

    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)
    Path(str(TEST_BOOTSTRAP) + ".tmp").unlink(missing_ok=True)


def _clear_memories(session) -> None:
    """按外键依赖顺序清空认知记忆，供独立场景测试使用。"""

    from sqlalchemy import text

    session.execute(text("DELETE FROM memory_change_proposals"))
    session.execute(text("DELETE FROM memory_confirmation_events"))
    session.execute(text("DELETE FROM cognitive_memory_evidence"))
    session.execute(text("UPDATE cognitive_memories SET current_revision_id = NULL"))
    session.execute(text("DELETE FROM cognitive_memory_revisions"))
    session.execute(text("DELETE FROM cognitive_memories"))


def _seed_completed_analysis(monkeypatch) -> dict:
    """创建一条带 Claims 与 Delta 的已完成分析，返回 ID 集合。"""

    from uuid import uuid4

    unique = uuid4().hex[:12]
    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(main_module, "utc_now", lambda: fixed_now)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    def relations_factory(user_prompt) -> list[CompareRelation]:
        payload = json.loads(user_prompt)
        candidates = payload["current_memory_candidates"]
        return [
            CompareRelation(
                current_claim_id="claim-001",
                primary_relation="duplicate",
                matches=[
                    {
                        "memory_revision_id": candidates[0]["revision_id"],
                        "candidate_kind": "current",
                        "relation": "duplicate",
                        "reason": "同一核心信息",
                    }
                ],
                reason="重复",
                confidence="high",
            ),
            CompareRelation(
                current_claim_id="claim-002",
                primary_relation="new",
                matches=[],
                reason="没有对应项",
                confidence="medium",
            ),
        ]

    with SessionLocal.begin() as session:
        _clear_memories(session)
        memory, revision = create_memory(
            session,
            statement="方法 X 在条件 A 下有效",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            entities=["MCP"],
        )

    with SessionLocal.begin() as session:
        content = Content(
            capture_id=f"capture-feedback-{unique}",
            source_type="web",
            source_url=f"https://example.com/feedback/{unique}",
            canonical_url=f"https://example.com/feedback/{unique}",
            capture_mode="manual",
            title="Feedback 测试文章",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])
        session.flush()
        analysis_id = analysis.id

    assert process_next_job(FullProvider(relations_factory=relations_factory)) is True
    with SessionLocal() as session:
        stored = session.get(Analysis, analysis_id)
        claim = session.scalar(
            select(ContentClaim).where(ContentClaim.analysis_id == analysis_id)
        )
        assert stored.status == "completed"
        assert stored.cognitive_compare_run_id is not None
        return {
            "analysis_id": analysis_id,
            "content_id": content.id,
            "claim_core_id": claim.claim_id,
            "claim_row_id": claim.id,
            "memory_id": memory.id,
            "revision_id": revision.id,
        }


def test_evaluate_input_carries_delta_summary() -> None:
    """Evaluate 输入包含代码生成的认知差异；为空时保持保守。"""

    analysis = AnalyzeContent(
        one_sentence_summary="测试。",
        summary="摘要。",
        content_profile={
            "topics": ["测试"],
            "content_type": "技术文章",
            "difficulty": "introductory",
        },
        content_map=[],
        key_points=[],
        claims=[],
        thesis=None,
        supporting_evidence=[],
        counterarguments=[],
        author_stance=None,
        limitations=[],
        unresolved_questions=[],
        unverified_claims=[],
    )
    profile = UserProfile(focus_topics=["测试"])
    state = CurrentUserState(active_goals=["设计 Memory V1"])
    with_delta = json.loads(
        evaluate_input(
            analysis,
            profile,
            state,
            {"known_duplicate_claim_ids": ["claim-001"], "retrieval_context_status": "sufficient"},
        )
    )
    assert with_delta["cognitive_delta"]["known_duplicate_claim_ids"] == ["claim-001"]
    without = json.loads(evaluate_input(analysis, profile, state))
    assert without["cognitive_delta"] is None


def test_claim_feedback_creates_memory_and_saves_root_cause(monkeypatch) -> None:
    """Claim 级反馈：不同认知创建 Memory，根因分流记录保存。"""

    ids = _seed_completed_analysis(monkeypatch)
    monkeypatch.setattr(
        main_module,
        "build_provider_from_settings",
        lambda: FullProvider(match_decision="different"),
    )
    with TestClient(main_module.app) as client:
        password = next(
            line.removeprefix("password=")
            for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
            if line.startswith("password=")
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": password},
        )
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

        # 第一条 Claim 已是 known duplicate：确认后只追加 Confirmation Event。
        first = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-001/feedback",
            json={"awareness": "known", "root_cause": "compare_relation_change"},
        )
        assert first.status_code == 200
        assert first.json()["outcome"] == "confirmed"
        assert first.json()["memory_id"] == ids["memory_id"]

        # 第二条 Claim（new）：用户确认新学到 → 创建新 Memory。
        second = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-002/feedback",
            json={"awareness": "known", "stance": "accept"},
        )
        assert second.status_code == 200
        assert second.json()["outcome"] == "created"
        assert second.json()["memory_id"] != ids["memory_id"]

        # 根因分流与用户动作被持久化。
        with SessionLocal() as session:
            events = session.scalars(
                select(ClaimFeedbackEvent).where(
                    ClaimFeedbackEvent.analysis_id == ids["analysis_id"]
                )
            ).all()
            assert len(events) == 2
            assert events[0].root_cause == "compare_relation_change"
            assert events[0].awareness == "known"
            assert events[1].stance == "accept"

        # 空反馈被拒绝。
        empty = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-001/feedback",
            json={"root_cause": "state_error"},
        )
        assert empty.status_code == 422


def test_primary_relation_correction_keeps_original_and_shows_effective(monkeypatch) -> None:
    """高级纠错：new 改为 extends 保留原始值，详情展示 effective。"""

    ids = _seed_completed_analysis(monkeypatch)
    with TestClient(main_module.app) as client:
        password = next(
            line.removeprefix("password=")
            for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
            if line.startswith("password=")
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": password},
        )
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

        # 无证据地把 new 改为 extends：允许保存，但 evidence_status = incomplete。
        correction = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-002/correction",
            json={
                "correction_type": "primary_relation",
                "corrected_value": "extends",
                "reason": "实际是对已有认识的扩展",
            },
        )
        assert correction.status_code == 200
        body = correction.json()
        assert body["original_value"] == "new"
        assert body["corrected_value"] == "extends"
        assert body["evidence_status"] == "incomplete"

        # 与原始值相同的纠错被拒绝。
        same = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-001/correction",
            json={"correction_type": "primary_relation", "corrected_value": "duplicate"},
        )
        assert same.status_code == 409

        # 详情 Delta 展示原始与 effective 两种值。
        detail = client.get(f"/api/v1/contents/{ids['content_id']}").json()
        delta = detail["cognitive_delta"]
        assert delta["relations"][1]["primary_relation"] == "new"
        assert delta["effective_relations"][1]["primary_relation"] == "extends"
        assert delta["claim_corrections"][0]["corrected_value"] == "extends"
        assert delta["claim_corrections"][0]["original_value"] == "new"

        # claim_role 纠错：evidence_status = not_applicable。
        role = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-002/correction",
            json={
                "correction_type": "claim_role",
                "corrected_value": "supporting",
                "reason": "这是重要支撑而非边缘细节",
            },
        )
        assert role.status_code == 200
        assert role.json()["evidence_status"] == "not_applicable"
        assert role.json()["original_value"] == "detail"


def test_primary_relation_correction_rejects_foreign_evidence(monkeypatch) -> None:
    """证据 Revision 必须来自当次候选集合，否则纠错被拒绝。"""

    ids = _seed_completed_analysis(monkeypatch)
    with TestClient(main_module.app) as client:
        password = next(
            line.removeprefix("password=")
            for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
            if line.startswith("password=")
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": password},
        )
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

        foreign = client.post(
            f"/api/v1/analyses/{ids['analysis_id']}/claims/claim-002/correction",
            json={
                "correction_type": "primary_relation",
                "corrected_value": "extends",
                "matched_memory_revision_ids": ["not-in-candidates"],
            },
        )
        assert foreign.status_code == 422

        # 不存在分析或 Claim 返回 404 而不是 5xx。
        missing = client.post(
            "/api/v1/analyses/not-exist/claims/claim-001/correction",
            json={"correction_type": "primary_relation", "corrected_value": "extends"},
        )
        assert missing.status_code == 404
