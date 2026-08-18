"""Claims 行级持久化与旧分析兼容的单元测试。"""

import os
from datetime import UTC, datetime
from pathlib import Path

# 与 test_api.py 共用同一个文件数据库：模块导入期 env 决定 engine 绑定。
TEST_DB = Path(__file__).with_name("test.db")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"

from sqlalchemy import select

import signallens.worker as worker_module
from signallens.analysis.claims import (
    ensure_content_revision,
    load_claim_rows,
    persist_claims,
    with_normalized_claims,
)
from signallens.analysis.schemas import AnalyzeContent, EvaluateForUser, TriageContent
from signallens.database import SessionLocal, create_schema, engine
from signallens.models import Analysis, AnalysisJob, Content
from signallens.worker import process_next_job


class FakeProvider:
    """为 Worker 回归测试提供确定性的三阶段结构化结果。"""

    model = "fake-test-model"

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
                claims=[],
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
        raise AssertionError(f"未处理的输出模型：{output_model}")


def setup_module() -> None:
    """每个测试文件只建一次共享数据库结构。"""

    create_schema()


def teardown_module() -> None:
    """显式释放 SQLite 文件句柄，再删除临时数据库。"""

    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)


def _content_analysis_with_claims(claims: list[dict]) -> AnalyzeContent:
    """构造携带指定 Claims 的内容分析对象。"""

    return AnalyzeContent(
        one_sentence_summary="测试文章。",
        summary="测试摘要。",
        content_profile={
            "topics": ["测试"],
            "content_type": "技术文章",
            "difficulty": "introductory",
        },
        content_map=[],
        key_points=[],
        claims=claims,
        thesis=None,
        supporting_evidence=[],
        counterarguments=[],
        author_stance=None,
        limitations=[],
        unresolved_questions=[],
        unverified_claims=[],
    )


def _make_analysis() -> tuple[Content, Analysis]:
    """创建一条已完成 analyze 阶段的测试分析。"""

    from uuid import uuid4

    unique = uuid4().hex[:12]
    with SessionLocal.begin() as session:
        content = Content(
            capture_id=f"capture-claims-{unique}",
            source_type="web",
            source_url=f"https://example.com/claims/{unique}",
            canonical_url=f"https://example.com/claims/{unique}",
            capture_mode="manual",
            title="Claims 测试文章",
            markdown="# 第一章\n\n正文。\n\n# 第二章\n\n更多正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content, status="running")
        job = AnalysisJob(analysis=analysis, stage="persist_claims", status="running")
        session.add_all([content, analysis, job])
        return content, analysis


def test_legacy_claims_are_normalized_with_safe_defaults() -> None:
    """旧格式 Claims 补齐缺省字段，保证新 Schema 可以继续解析。"""

    payload = {
        "summary": "旧摘要",
        "claims": [
            {
                "claim": "旧格式主张",
                "evidence": ["原文证据"],
                "verification": "supported_in_content",
            }
        ],
    }
    normalized = with_normalized_claims(payload)
    claim = normalized["claims"][0]
    assert claim["claim_type"] == "interpretation"
    assert claim["claim_role"] == "detail"
    assert claim["change_signal"] == "none"
    assert claim["section_ref"] is None
    assert claim["topics"] == []
    assert claim["entities"] == []
    assert claim["claim_id"] is None
    # 规范化后的 Claim 必须能通过新契约校验。
    result = AnalyzeContent.model_validate(
        {
            "one_sentence_summary": "测试文章。",
            "summary": "测试摘要。",
            "content_profile": {
                "topics": ["测试"],
                "content_type": "技术文章",
                "difficulty": "introductory",
            },
            "content_map": [],
            "key_points": [],
            "claims": [claim],
            "thesis": None,
            "supporting_evidence": [],
            "counterarguments": [],
            "author_stance": None,
            "limitations": [],
            "unresolved_questions": [],
            "unverified_claims": [],
        }
    )
    assert result.claims[0].claim == "旧格式主张"


def test_persist_claims_assigns_stable_ids_and_writes_rows() -> None:
    """持久化阶段分配分析内稳定 claim_id，并把行级记录写回 JSON。"""

    _, analysis = _make_analysis()
    claims = [
        {
            "claim": "核心主张：新方法有效",
            "claim_type": "fact",
            "claim_role": "core",
            "change_signal": "none",
            "section_ref": "sec-001",
            "evidence": ["实验数据"],
            "verification": "supported_in_content",
            "topics": ["Agent Memory"],
            "entities": ["MCP"],
        },
        {
            "claim": "细节：参数取值",
            "claim_type": "fact",
            "claim_role": "detail",
            "change_signal": "none",
            "section_ref": "sec-999",
            "evidence": ["原文例子"],
            "verification": "unverified",
            "topics": [],
            "entities": [],
        },
    ]
    with SessionLocal.begin() as session:
        analysis = session.get(Analysis, analysis.id)
        analysis.content_analysis_json = _content_analysis_with_claims(claims).model_dump(
            mode="json"
        )
        analysis.section_index_json = {
            "primary_heading_level": 1,
            "sections": [
                {
                    "section_ref": "sec-001",
                    "level": 1,
                    "title": "第一章",
                    "order": 1,
                    "start_line": 0,
                    "end_line": 3,
                }
            ],
        }

    with SessionLocal.begin() as session:
        persist_claims(
            session,
            analysis_id=analysis.id,
            content_revision_id=None,
            model="fake-test-model",
            prompt_version="v0.5.0",
        )

    with SessionLocal() as session:
        stored = load_claim_rows(session, analysis.id)
        assert len(stored) == 2
        first, second = stored
        # 第一条合法引用保留；第二条模型编造的引用必须置空而不是伪造。
        assert first.claim_id == "claim-001"
        assert first.section_ref == "sec-001"
        assert first.claim_role == "core"
        assert second.claim_id == "claim-002"
        assert second.section_ref is None
        # JSON 中写回稳定 ID，供后续 Compare / Evaluate 引用。
        payload = session.get(Analysis, analysis.id).content_analysis_json
        assert payload["claims"][0]["claim_id"] == "claim-001"
        assert payload["claims"][1]["claim_id"] == "claim-002"
        assert payload["claims"][1]["section_ref"] is None


def test_persist_claims_is_idempotent() -> None:
    """同一分析重复落库不重复插入，已有 claim_id 保持不变。"""

    _, analysis = _make_analysis()
    claims = [
        {
            "claim": "重复运行的主张",
            "claim_type": "opinion",
            "claim_role": "supporting",
            "change_signal": "none",
            "section_ref": None,
            "evidence": [],
            "verification": "opinion",
            "topics": [],
            "entities": [],
        }
    ]
    with SessionLocal.begin() as session:
        analysis = session.get(Analysis, analysis.id)
        analysis.content_analysis_json = _content_analysis_with_claims(claims).model_dump(
            mode="json"
        )

    for _ in range(2):
        with SessionLocal.begin() as session:
            persist_claims(
                session,
                analysis_id=analysis.id,
                content_revision_id=None,
                model="fake-test-model",
                prompt_version="v0.5.0",
            )

    with SessionLocal() as session:
        stored = load_claim_rows(session, analysis.id)
        assert len(stored) == 1
        assert stored[0].claim_id == "claim-001"
        payload = session.get(Analysis, analysis.id).content_analysis_json
        assert payload["claims"][0]["claim_id"] == "claim-001"


def test_ensure_content_revision_is_idempotent_per_hash() -> None:
    """同一内容的同一正文哈希只创建一次 Revision；正文变化创建新版本。"""

    content, _ = _make_analysis()
    with SessionLocal.begin() as session:
        first = ensure_content_revision(
            session,
            content_id=content.id,
            source_hash="hash-a",
            title=content.title,
            markdown=content.markdown,
        )
        second = ensure_content_revision(
            session,
            content_id=content.id,
            source_hash="hash-a",
            title=content.title,
            markdown=content.markdown,
        )
        third = ensure_content_revision(
            session,
            content_id=content.id,
            source_hash="hash-b",
            title=content.title,
            markdown="新正文",
        )
        assert first.id == second.id
        assert first.version == 1
        assert third.version == 2
        assert third.markdown == "新正文"


def test_worker_persists_claims_stage_and_completes(monkeypatch) -> None:
    """Worker 全流程：analyze 后先落 Claims 再进入 evaluate。"""

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    with SessionLocal.begin() as session:
        content = Content(
            capture_id="capture-claims-0002",
            source_type="web",
            source_url="https://example.com/worker-claims",
            canonical_url="https://example.com/worker-claims",
            capture_mode="manual",
            title="Worker Claims 测试",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])

    assert process_next_job(FakeProvider()) is True
    with SessionLocal() as session:
        stored = session.scalars(select(Analysis).where(Analysis.id == analysis.id)).one()
        assert stored.status == "completed"
        assert stored.content_revision_id is not None
        # FakeProvider 不返回 Claims；无行级记录是合法状态，不阻断分析完成。
        assert load_claim_rows(session, analysis.id) == []
