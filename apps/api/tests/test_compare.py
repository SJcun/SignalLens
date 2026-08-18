"""Cognitive Compare 结构校验、Delta 聚合与 Worker 阶段的测试。"""

import os
from datetime import UTC, datetime
from pathlib import Path

TEST_DB = Path(__file__).with_name("test.db")
TEST_BOOTSTRAP = Path(__file__).with_name("initial-admin-password.txt")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SIGNALLENS_BOOTSTRAP_PASSWORD_FILE"] = str(TEST_BOOTSTRAP)

import pytest

import signallens.worker as worker_module
from signallens.analysis.compare import (
    CognitiveCompare,
    CompareRelation,
    CompareValidationError,
    derive_delta_summary,
    validate_compare_output,
)
from signallens.analysis.retrieval import retrieve_memory_candidates
from signallens.analysis.schemas import AnalyzeContent, EvaluateForUser, TriageContent
from signallens.database import SessionLocal, create_schema, engine
from signallens.memory import create_memory
from signallens.models import (
    Analysis,
    AnalysisJob,
    CognitiveCompareRun,
    Content,
)
from signallens.worker import process_next_job

RELATION_CLAIMS = [
    {
        "claim_id": "claim-001",
        "claim": "核心主张：新方法在条件 A 下有效",
        "claim_role": "core",
        "change_signal": "none",
        "topics": ["Agent Memory"],
        "entities": ["MCP"],
    },
    {
        "claim_id": "claim-002",
        "claim": "细节：参数取值为 3",
        "claim_role": "detail",
        "change_signal": "none",
        "topics": [],
        "entities": [],
    },
    {
        "claim_id": "claim-003",
        "claim": "新版本 API 已改为 Y",
        "claim_role": "supporting",
        "change_signal": "version",
        "topics": ["API"],
        "entities": ["MCP"],
    },
]


class CompareProvider:
    """按脚本返回 Compare 关系，用于聚合与校验测试。"""

    model = "compare-test-model"

    def __init__(self, relations_factory):
        self.relations_factory = relations_factory

    def complete(self, *, system_prompt, user_prompt, output_model):
        """返回由工厂函数生成的关系输出。"""

        assert output_model is CognitiveCompare
        return CognitiveCompare(relations=self.relations_factory(user_prompt))


def _duplicate_relations(user_prompt) -> list[CompareRelation]:
    """Case 1 与 Case 3：核心重复、细节新增。"""

    import json

    payload = json.loads(user_prompt)
    candidates = payload["current_memory_candidates"]
    core_match = next((c for c in candidates if "核心主张" in c["statement"]), candidates[0])
    return [
        CompareRelation(
            current_claim_id="claim-001",
            primary_relation="duplicate",
            matches=[
                {
                    "memory_revision_id": core_match["revision_id"],
                    "candidate_kind": "current",
                    "relation": "duplicate",
                    "reason": "表达同一核心信息",
                }
            ],
            reason="与已确认认知重复",
            confidence="high",
        ),
        CompareRelation(
            current_claim_id="claim-002",
            primary_relation="new",
            matches=[],
            reason="本次召回的 Memory 中没有对应项",
            confidence="medium",
        ),
    ]


def test_compare_output_structural_validation() -> None:
    """new 带 match、引用未检查候选等违规输出必须被拒绝。"""

    current_ids = ["rev-a"]
    historical_ids = ["rev-b"]
    claim_ids = ["claim-001"]

    # new 关系携带 match：非法。
    with pytest.raises(CompareValidationError, match="new 关系不得携带 match 证据"):
        validate_compare_output(
            CognitiveCompare(
                relations=[
                    CompareRelation(
                        current_claim_id="claim-001",
                        primary_relation="new",
                        matches=[
                            {
                                "memory_revision_id": "rev-a",
                                "candidate_kind": "current",
                                "relation": "duplicate",
                                "reason": "x",
                            }
                        ],
                        reason="x",
                        confidence="high",
                    )
                ]
            ),
            claim_ids=claim_ids,
            current_candidate_ids=current_ids,
            historical_candidate_ids=historical_ids,
        )

    # 非 new 关系必须引用候选集合内的 Revision。
    with pytest.raises(CompareValidationError, match="未检查的 current Revision"):
        validate_compare_output(
            CognitiveCompare(
                relations=[
                    CompareRelation(
                        current_claim_id="claim-001",
                        primary_relation="duplicate",
                        matches=[
                            {
                                "memory_revision_id": "rev-unknown",
                                "candidate_kind": "current",
                                "relation": "duplicate",
                                "reason": "x",
                            }
                        ],
                        reason="x",
                        confidence="high",
                    )
                ]
            ),
            claim_ids=claim_ids,
            current_candidate_ids=current_ids,
            historical_candidate_ids=historical_ids,
        )

    # contradicts 必须提供冲突摘要。
    with pytest.raises(CompareValidationError, match="冲突摘要"):
        validate_compare_output(
            CognitiveCompare(
                relations=[
                    CompareRelation(
                        current_claim_id="claim-001",
                        primary_relation="contradicts",
                        matches=[
                            {
                                "memory_revision_id": "rev-a",
                                "candidate_kind": "current",
                                "relation": "contradicts",
                                "reason": "x",
                            }
                        ],
                        reason="x",
                        confidence="high",
                    )
                ]
            ),
            claim_ids=claim_ids,
            current_candidate_ids=current_ids,
            historical_candidate_ids=historical_ids,
        )

    # Claim 集合必须与输入完全一致。
    with pytest.raises(CompareValidationError, match="与输入不一致"):
        validate_compare_output(
            CognitiveCompare(
                relations=[
                    CompareRelation(
                        current_claim_id="claim-999",
                        primary_relation="new",
                        matches=[],
                        reason="x",
                        confidence="high",
                    )
                ]
            ),
            claim_ids=claim_ids,
            current_candidate_ids=current_ids,
            historical_candidate_ids=historical_ids,
        )


def test_delta_summary_distinguishes_known_duplicate_and_gain() -> None:
    """代码聚合：known duplicate 与认知增量按角色分层统计。"""

    output = CognitiveCompare(
        relations=[
            CompareRelation(
                current_claim_id="claim-001",
                primary_relation="duplicate",
                matches=[
                    {
                        "memory_revision_id": "rev-known",
                        "candidate_kind": "current",
                        "relation": "duplicate",
                        "reason": "相同",
                    }
                ],
                reason="重复",
                confidence="high",
            ),
            CompareRelation(
                current_claim_id="claim-002",
                primary_relation="new",
                matches=[],
                reason="无对应项",
                confidence="medium",
            ),
            CompareRelation(
                current_claim_id="claim-003",
                primary_relation="updates",
                matches=[
                    {
                        "memory_revision_id": "rev-obsolete",
                        "candidate_kind": "historical",
                        "relation": "updates",
                        "reason": "版本替代",
                    }
                ],
                reason="新版本替代旧版本",
                confidence="high",
            ),
        ]
    )
    summary = derive_delta_summary(
        output,
        claims=RELATION_CLAIMS,
        current_candidate_ids=["rev-known"],
        historical_candidate_ids=["rev-obsolete"],
        current_revision_awareness={"rev-known": "known"},
        retrieval_context={"status": "sufficient"},
    )
    assert summary["known_duplicate_claim_ids"] == ["claim-001"]
    assert summary["uncertain_overlap_claim_ids"] == []
    assert summary["duplicate_claim_ids"] == ["claim-001"]
    # new / updates 都构成认知增量；historical 引用的 updates 也计入。
    assert set(summary["cognitive_gain_claim_ids"]) == {"claim-002", "claim-003"}
    assert summary["detail_gain_claim_ids"] == ["claim-002"]
    assert summary["supporting_gain_claim_ids"] == ["claim-003"]
    assert summary["relation_counts_by_role"]["core"] == {"duplicate": 1}
    assert summary["relation_counts_by_role"]["detail"] == {"new": 1}
    assert summary["unused_candidate_memory_revision_ids"] == []


def test_uncertain_awareness_duplicate_is_not_known() -> None:
    """引用 uncertain Revision 的 duplicate 不能进入"用户已知"聚合。"""

    output = CognitiveCompare(
        relations=[
            CompareRelation(
                current_claim_id="claim-001",
                primary_relation="duplicate",
                matches=[
                    {
                        "memory_revision_id": "rev-uncertain",
                        "candidate_kind": "current",
                        "relation": "duplicate",
                        "reason": "语义重合",
                    }
                ],
                reason="重合",
                confidence="medium",
            )
        ]
    )
    summary = derive_delta_summary(
        output,
        claims=RELATION_CLAIMS,
        current_candidate_ids=["rev-uncertain"],
        historical_candidate_ids=[],
        current_revision_awareness={"rev-uncertain": "uncertain"},
        retrieval_context={"status": "sufficient"},
    )
    assert summary["known_duplicate_claim_ids"] == []
    assert summary["uncertain_overlap_claim_ids"] == ["claim-001"]


def test_retrieval_context_status_rules() -> None:
    """无 Memory、全量扫描、候选截断分别产生对应状态。"""

    claims = [
        {
            "claim_id": "claim-001",
            "claim": "主张",
            "change_signal": "none",
            "topics": ["X"],
            "entities": [],
        }
    ]
    # 空库：无 active 也无 obsolete → insufficient。
    with SessionLocal.begin() as session:
        session.query(CognitiveCompareRun).delete()
        _clear_memories(session)
        result = retrieve_memory_candidates(session, claims)
        assert result.context.status == "insufficient"
        assert "no_active_memory" in result.context.reason_codes

    # 少量 active Memory 视为全量扫描，状态 sufficient。
    with SessionLocal.begin() as session:
        create_memory(
            session,
            statement="匹配主题 X 的认知",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            topics=["X"],
        )
        result = retrieve_memory_candidates(session, claims)
        assert result.context.status == "sufficient"
        assert result.context.all_active_scanned is True
        assert len(result.current_revision_ids) == 1

    # change signal 触发 obsolete 历史召回。
    with SessionLocal.begin() as session:
        _memory, revision = create_memory(
            session,
            statement="旧版本使用 X",
            awareness_state="known",
            stance="accept",
            lifecycle="obsolete",
            source_type="manual",
            entities=["MCP"],
        )
        version_claim = [
            {
                "claim_id": "claim-001",
                "claim": "新版本已改为 Y",
                "change_signal": "version",
                "topics": [],
                "entities": ["MCP"],
            }
        ]
        result = retrieve_memory_candidates(session, version_claim)
        assert result.context.historical_recall_triggered is True
        assert result.context.historical_candidate_count == 1
        assert revision.id in result.historical_revision_ids


def test_worker_compare_stage_and_delta_persistence(monkeypatch) -> None:
    """Worker 全流程执行 Compare 并持久化 Delta；详情可读取。"""

    import json

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    with SessionLocal.begin() as session:
        _clear_memories(session)
        create_memory(
            session,
            statement="核心主张：新方法在条件 A 下有效",
            awareness_state="known",
            stance="reject",  # 知道但反对，仍应判 duplicate
            source_type="manual",
            entities=["MCP"],
        )

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
                        "reason": "同一核心信息，用户立场不影响关系",
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

    provider = ClaimsProvider(relations_factory)
    with SessionLocal.begin() as session:
        content = Content(
            capture_id="capture-compare-0001",
            source_type="web",
            source_url="https://example.com/compare",
            canonical_url="https://example.com/compare",
            capture_mode="manual",
            title="Compare 测试文章",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])

    assert process_next_job(provider) is True

    with SessionLocal() as session:
        stored = session.get(Analysis, analysis.id)
        assert stored.status == "completed"
        assert stored.retrieval_context_status == "sufficient"
        run = session.get(CognitiveCompareRun, stored.cognitive_compare_run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.derived_summary_json["known_duplicate_claim_ids"] == ["claim-001"]
        assert set(run.derived_summary_json["cognitive_gain_claim_ids"]) == {"claim-002"}
        assert run.retrieval_context_json["status"] == "sufficient"
        assert run.retrieval_context_json["current_candidate_count"] == 1


def test_compare_failure_degrades_to_conservative_evaluate(monkeypatch) -> None:
    """Compare 失败不阻塞分析：保守 Evaluate 完成，Compare 可单独重试。"""

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    with SessionLocal.begin() as session:
        _clear_memories(session)
        create_memory(
            session,
            statement="核心主张：新方法在条件 A 下有效",
            awareness_state="known",
            stance="accept",
            source_type="manual",
            entities=["MCP"],
        )

    class FailingCompareProvider(ClaimsProvider):
        model = "failing-compare-model"

        def complete(self, *, system_prompt, user_prompt, output_model):
            if output_model is CognitiveCompare:
                raise RuntimeError("模拟 Compare 模型错误")
            return super().complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=output_model,
            )

    with SessionLocal.begin() as session:
        content = Content(
            capture_id="capture-compare-0002",
            source_type="web",
            source_url="https://example.com/compare-fail",
            canonical_url="https://example.com/compare-fail",
            capture_mode="manual",
            title="Compare 失败测试",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])

    assert process_next_job(FailingCompareProvider()) is True

    with SessionLocal() as session:
        stored = session.get(Analysis, analysis.id)
        assert stored.status == "completed"
        assert stored.personal_evaluation_json is not None
        run = session.get(CognitiveCompareRun, stored.cognitive_compare_run_id)
        assert run.status == "failed"
        assert run.last_error is not None
        assert stored.cognitive_compare_run_id is not None


def _clear_memories(session) -> None:
    """按外键依赖顺序清空认知记忆，供独立场景测试使用。"""

    from sqlalchemy import text

    session.execute(text("DELETE FROM memory_change_proposals"))
    session.execute(text("DELETE FROM memory_confirmation_events"))
    session.execute(text("DELETE FROM cognitive_memory_evidence"))
    session.execute(text("UPDATE cognitive_memories SET current_revision_id = NULL"))
    session.execute(text("DELETE FROM cognitive_memory_revisions"))
    session.execute(text("DELETE FROM cognitive_memories"))


class ClaimsProvider:
    """返回带 Claims 的内容分析，并支持 Compare 输出。"""

    model = "claims-test-model"

    def __init__(self, relations_factory=None):
        self.relations_factory = relations_factory

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
                        "claim": "核心主张：新方法在条件 A 下有效",
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
        raise AssertionError(f"未处理的输出模型：{output_model}")


def setup_module() -> None:
    """每个测试文件只建一次共享数据库结构。"""

    create_schema()


def teardown_module() -> None:
    """显式释放 SQLite 文件句柄，再删除临时数据库。"""

    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)
