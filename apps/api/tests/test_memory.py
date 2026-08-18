"""Cognitive Memory 匹配、确认与修改建议的单元及 API 测试。"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

TEST_DB = Path(__file__).with_name("test.db")
TEST_BOOTSTRAP = Path(__file__).with_name("initial-admin-password.txt")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SIGNALLENS_BOOTSTRAP_PASSWORD_FILE"] = str(TEST_BOOTSTRAP)

from fastapi.testclient import TestClient

import signallens.main as main_module
from signallens.database import SessionLocal, create_schema, engine
from signallens.memory import (
    MemoryMatchJudgment,
    apply_claim_feedback,
    apply_proposal_decision,
    create_memory,
    run_memory_match,
)
from signallens.models import (
    CognitiveMemory,
    CognitiveMemoryRevision,
    Content,
    ContentClaim,
    MemoryChangeProposal,
)


class MatchProvider:
    """按脚本返回 Memory Match 判断，用于确定性匹配分支测试。"""

    model = "match-test-model"

    def __init__(self, decision="equivalent", confidence="high"):
        self.decision = decision
        self.confidence = confidence

    def complete(self, *, system_prompt, user_prompt, output_model):
        """从候选 Revision 中选取第一条作为等价匹配。"""

        assert output_model is MemoryMatchJudgment
        candidates = json.loads(user_prompt)["candidate_revisions"]
        if self.decision == "equivalent":
            target = candidates[0]
            return MemoryMatchJudgment(
                decision="equivalent",
                matched_memory_id=target["memory_id"],
                matched_memory_revision_id=target["revision_id"],
                confidence=self.confidence,
                reason="测试判断等价",
            )
        if self.decision == "different":
            return MemoryMatchJudgment(
                decision="different",
                confidence=self.confidence,
                reason="测试判断不同",
            )
        return MemoryMatchJudgment(
            decision="uncertain",
            confidence="low",
            reason="测试无法判断",
        )


def setup_module() -> None:
    """每个测试文件只建一次共享数据库结构。"""

    create_schema()


def teardown_module() -> None:
    """显式释放 SQLite 文件句柄，再删除临时数据库和凭据文件。"""

    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)
    Path(str(TEST_BOOTSTRAP) + ".tmp").unlink(missing_ok=True)


def _seed_claim(session, *, statement="方法 X 在条件 A 下有效", role="core") -> ContentClaim:
    """创建一条携带 Claim 的测试分析记录，返回行级 Claim。"""

    content = Content(
        capture_id=f"capture-memory-{statement[:8]}-{role}",
        source_type="web",
        source_url=f"https://example.com/memory/{statement[:8]}",
        canonical_url=f"https://example.com/memory/{statement[:8]}",
        capture_mode="manual",
        title="Memory 测试文章",
        markdown="# 第一章\n\n正文。",
        capture_quality="good",
        capture_payload_json={},
    )
    session.add(content)
    session.flush()
    from signallens.models import Analysis, AnalysisJob

    analysis = Analysis(
        content_id=content.id,
        status="completed",
        content_analysis_json={},
        source_hash="hash",
        prompt_version="v0.5.0",
    )
    session.add(analysis)
    session.flush()
    session.add(AnalysisJob(analysis_id=analysis.id, stage="completed", status="completed"))
    claim = ContentClaim(
        analysis_id=analysis.id,
        claim_id="claim-001",
        claim_order=1,
        statement=statement,
        claim_type="fact",
        claim_role=role,
        change_signal="none",
        evidence_json=[],
        verification="supported_in_content",
        topics_json=["Agent Memory"],
        entities_json=["MCP"],
        prompt_version="v0.5.0",
    )
    session.add(claim)
    session.flush()
    return claim


def _clear_memories(session) -> None:
    """按外键依赖顺序清空认知记忆，供独立场景测试使用。

    cognitive_memories 与 cognitive_memory_revisions 互相引用：
    先清空 current_revision_id 指针，再删 Revision，最后删逻辑身份。
    """

    from sqlalchemy import text

    session.execute(text("DELETE FROM memory_change_proposals"))
    session.execute(text("DELETE FROM memory_confirmation_events"))
    session.execute(text("DELETE FROM cognitive_memory_evidence"))
    session.execute(text("UPDATE cognitive_memories SET current_revision_id = NULL"))
    session.execute(text("DELETE FROM cognitive_memory_revisions"))
    session.execute(text("DELETE FROM cognitive_memories"))


def test_exact_text_match_confirms_without_duplicate() -> None:
    """规范化文本完全匹配时，重复录入只追加 Confirmation Event。"""

    with SessionLocal.begin() as session:
        memory, revision = create_memory(
            session,
            statement="方法 X 在条件 A 下有效",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            confirmed_at=datetime(2026, 8, 1, tzinfo=UTC),
        )

    with SessionLocal.begin() as session:
        match = run_memory_match(
            session,
            MatchProvider("equivalent", "high"),
            statement="方法X在条件A下有效",  # 标点/空白不同，规范化后相同
        )
        assert match.decision == "equivalent"
        assert match.match_source == "exact_text"
        assert match.matched_memory_id == memory.id

    with SessionLocal() as session:
        memory_after = session.get(CognitiveMemory, memory.id)
        revision_count = len(
            session.query(CognitiveMemoryRevision)
            .filter_by(cognitive_memory_id=memory.id)
            .all()
        )
        assert memory_after.current_revision_id == revision.id
        assert revision_count == 1


def test_entity_topic_recall_with_llm_equivalent_uses_high_confidence_only() -> None:
    """召回后语义判断：只有 high 置信的 equivalent 才允许自动合并。"""

    with SessionLocal.begin() as session:
        _memory, _revision = create_memory(
            session,
            statement="旧表述：MCP 支持工具调用",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            entities=["MCP"],
        )

    # 低置信等价不能自动采用，降级为 uncertain。
    with SessionLocal.begin() as session:
        match = run_memory_match(
            session,
            MatchProvider("equivalent", "medium"),
            statement="MCP 支持工具调用",
            entities=["MCP"],
        )
        assert match.decision == "uncertain"
        assert match.matched_memory_id is None


def test_llm_invalid_revision_id_is_rejected() -> None:
    """LLM 引用本次未检查的 Revision 时，结果必须降级为 uncertain。"""

    with SessionLocal.begin() as session:
        create_memory(
            session,
            statement="候选认知 A",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            entities=["A"],
        )
    with SessionLocal.begin() as session:
        match = run_memory_match(
            session,
            MatchProvider("equivalent", "high"),
            statement="候选认知 A 的另一种表达",
            entities=["A"],
        )
        assert match.decision == "equivalent"
        assert match.matched_memory_revision_id is not None


def test_different_without_candidates_creates_new_memory() -> None:
    """没有已确认候选时视为不同，直接创建新 Memory。"""

    with SessionLocal.begin() as session:
        # 清空此前测试创建的认知，保证本场景确实没有候选可召回。
        _clear_memories(session)
        match = run_memory_match(
            session,
            None,
            statement="全新领域的主张",
            topics=["全新主题"],
        )
        assert match.decision == "different"
        assert match.match_source == "none"


def test_uncertain_generates_resolve_match_proposal() -> None:
    """匹配不确定时生成 RESOLVE_MATCH Proposal，不自动合并或创建。"""

    with SessionLocal.begin() as session:
        _clear_memories(session)
        _memory, revision = create_memory(
            session,
            statement="候选认知 B",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            entities=["B"],
        )

    with SessionLocal.begin() as session:
        outcome, memory_id, proposal_id, _match = apply_claim_feedback(
            session,
            MatchProvider("uncertain", "low"),
            content_claim_id=_seed_claim(session, statement="候选认知 B 的变体").id,
        )
        assert outcome == "proposal"
        assert memory_id is None
        assert proposal_id is not None
        proposal = session.get(MemoryChangeProposal, proposal_id)
        assert proposal.action == "RESOLVE_MATCH"
        assert proposal.candidate_memory_revision_ids_json == [revision.id]
        assert proposal.status == "pending"


def test_proposal_reject_and_accept_revise() -> None:
    """拒绝保留记录；接受 REVISE 时校验期望版本并追加 Revision。"""

    with SessionLocal.begin() as session:
        memory, revision = create_memory(
            session,
            statement="原主张",
            awareness_state="known",
            stance="accept",
            source_type="manual",
        )
        proposal = MemoryChangeProposal(
            action="REVISE",
            target_memory_id=memory.id,
            expected_current_revision_id=revision.id,
            proposed_statement="修订后的主张",
            proposed_awareness_state="known",
            proposed_stance="mixed",
            proposed_lifecycle="active",
            reason="用户修正",
            status="pending",
        )
        session.add(proposal)
        session.flush()

    # 拒绝不改变正式状态。
    with SessionLocal.begin() as session:
        proposal, outcome, _ = apply_proposal_decision(
            session,
            None,
            proposal_id=proposal.id,
            decision="rejected",
        )
        assert outcome == "rejected"
        assert proposal.status == "rejected"
        assert session.get(CognitiveMemory, memory.id).current_revision_id == revision.id

    # 接受后追加新 Revision，指针原子更新。
    second_proposal_id = None
    with SessionLocal.begin() as session:
        second = MemoryChangeProposal(
            action="REVISE",
            target_memory_id=memory.id,
            expected_current_revision_id=revision.id,
            proposed_statement="修订后的主张",
            proposed_awareness_state="known",
            proposed_stance="mixed",
            proposed_lifecycle="active",
            reason="用户修正",
            status="pending",
        )
        session.add(second)
        session.flush()
        second_proposal_id = second.id
    with SessionLocal.begin() as session:
        proposal, outcome, memory_id = apply_proposal_decision(
            session,
            None,
            proposal_id=second_proposal_id,
            decision="accepted",
        )
        assert outcome == "revised"
        assert proposal.status == "accepted"
        memory_after = session.get(CognitiveMemory, memory_id)
        assert memory_after.current_revision_id != revision.id
        current = session.get(CognitiveMemoryRevision, memory_after.current_revision_id)
        assert current.statement == "修订后的主张"
        assert current.stance == "mixed"


def test_proposal_stale_when_expected_revision_changed() -> None:
    """期望版本已变化时 Proposal 标记 stale，不能覆盖较新修改。"""

    with SessionLocal.begin() as session:
        memory, revision = create_memory(
            session,
            statement="原主张",
            awareness_state="known",
            stance="accept",
            source_type="manual",
        )
        proposal = MemoryChangeProposal(
            action="REVISE",
            target_memory_id=memory.id,
            expected_current_revision_id=revision.id,
            proposed_statement="过期建议",
            proposed_awareness_state="known",
            proposed_stance="accept",
            proposed_lifecycle="active",
            status="pending",
        )
        session.add(proposal)
        session.flush()
        from signallens.memory import append_memory_revision

        # 用户先修改了一次，当前指针已经不是 proposal 看到的版本。
        append_memory_revision(
            session,
            memory.id,
            statement="用户的最新主张",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            expected_current_revision_id=revision.id,
        )

    from signallens.memory import MemoryRevisionConflict

    with SessionLocal.begin() as session:
        proposal = session.get(MemoryChangeProposal, proposal.id)
        try:
            apply_proposal_decision(
                session,
                None,
                proposal_id=proposal.id,
                decision="accepted",
            )
            raise AssertionError("应抛出版本冲突")
        except MemoryRevisionConflict:
            pass
        assert session.get(MemoryChangeProposal, proposal.id).status == "stale"


def test_memory_api_write_flow(monkeypatch) -> None:
    """手工录入 API：创建、等价确认、状态变化修订和版本冲突。"""

    from datetime import UTC, datetime

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(main_module, "utc_now", lambda: fixed_now)
    # API 端点使用统一 Provider 构造器；测试注入固定返回等价的 LLM 判断。
    monkeypatch.setattr(
        main_module,
        "build_provider_from_settings",
        lambda: MatchProvider("equivalent", "high"),
    )
    with SessionLocal.begin() as session:
        _clear_memories(session)

    with TestClient(main_module.app) as client:
        if TEST_BOOTSTRAP.exists():
            password = next(
                line.removeprefix("password=")
                for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
                if line.startswith("password=")
            )
        else:
            password = _bootstrap_password(client)
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": password},
        )
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

        # 第一次录入：无候选 → different → created。
        first = client.post(
            "/api/v1/memory",
            json={
                "statement": "MCP 工具调用协议已经稳定",
                "awareness_state": "known",
                "stance": "accept",
                "topics": ["Agent Memory"],
                "entities": ["MCP"],
            },
        )
        assert first.status_code == 200
        body = first.json()
        assert body["outcome"] == "created"
        assert body["memory"]["current_revision"]["version"] == 1
        memory_id = body["memory"]["id"]

        # 相同 statement 再次录入：exact_text → confirmed，不创建新 Memory/Revision。
        second = client.post(
            "/api/v1/memory",
            json={
                "statement": "MCP 工具调用协议已经稳定",
                "awareness_state": "known",
                "stance": "accept",
            },
        ).json()
        assert second["outcome"] == "confirmed"
        assert second["memory"]["id"] == memory_id
        assert second["memory"]["current_revision"]["version"] == 1

        # statement 变化：equivalent + 状态变化 → revised，追加版本。
        third = client.post(
            "/api/v1/memory",
            json={
                "statement": "MCP 工具调用协议已稳定且社区认可",
                "awareness_state": "known",
                "stance": "accept",
            },
        ).json()
        assert third["outcome"] == "revised"
        assert third["memory"]["id"] == memory_id
        assert third["memory"]["current_revision"]["version"] == 2

        # 追加 Revision 时期望版本过期 → 409。
        conflict = client.post(
            f"/api/v1/memory/{memory_id}/revisions",
            json={
                "expected_current_revision_id": "wrong-revision-id",
                "awareness_state": "known",
            },
        )
        assert conflict.status_code == 409
        assert "已变化" in conflict.json()["detail"]

        # 追加 Revision 成功：只改 stance，其他维度保持。
        revised = client.post(
            f"/api/v1/memory/{memory_id}/revisions",
            json={
                "expected_current_revision_id": third["memory"]["current_revision"]["id"],
                "stance": "mixed",
            },
        )
        assert revised.status_code == 200
        assert revised.json()["outcome"] == "revised"
        assert revised.json()["memory"]["current_revision"]["stance"] == "mixed"
        assert revised.json()["memory"]["current_revision"]["awareness_state"] == "known"

        # 列表与详情包含完整版本历史。
        memory_list = client.get("/api/v1/memory").json()
        assert len(memory_list) == 1
        assert memory_list[0]["revision_count"] == 3
        detail = client.get(f"/api/v1/memory/{memory_id}").json()
        assert len(detail["revisions"]) == 3
        assert len(detail["confirmation_events"]) >= 1


def _bootstrap_password(client) -> str:
    """TestClient lifespan 已创建 admin；读取新写入的凭据文件。"""

    return next(
        line.removeprefix("password=")
        for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
        if line.startswith("password=")
    )
