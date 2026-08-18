"""Memory 候选召回与代码计算的 Retrieval Context。

第一版不引入向量数据库：候选分 current（active 当前指针）与 historical
（仅 change signal 触发时召回的 obsolete 当前指针）两组。召回只缩小
候选范围，不决定语义关系；上下文状态由确定性代码计算，LLM 不能修改。
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CognitiveMemory, CognitiveMemoryRevision

# 传给 Compare 的候选总数上限；超过时标记 truncated 并按实体优先截断。
MAX_CANDIDATES = 24
# active Memory 数量不超过该值时视为"全量扫描"。
FULL_SCAN_THRESHOLD = 30


@dataclass
class RetrievalContext:
    """本次 Compare 的召回上下文状态与原因。"""

    status: str = "insufficient"
    total_active_revision_count: int = 0
    total_obsolete_revision_count: int = 0
    entity_match_count: int = 0
    topic_match_count: int = 0
    candidate_count: int = 0
    current_candidate_count: int = 0
    historical_candidate_count: int = 0
    historical_recall_triggered: bool = False
    all_active_scanned: bool = False
    all_eligible_historical_scanned: bool = False
    truncated: bool = False
    retrieval_error: str | None = None
    reason_codes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """转换为可持久化的稳定字典。"""

        return {
            "status": self.status,
            "total_active_revision_count": self.total_active_revision_count,
            "total_obsolete_revision_count": self.total_obsolete_revision_count,
            "entity_match_count": self.entity_match_count,
            "topic_match_count": self.topic_match_count,
            "candidate_count": self.candidate_count,
            "current_candidate_count": self.current_candidate_count,
            "historical_candidate_count": self.historical_candidate_count,
            "historical_recall_triggered": self.historical_recall_triggered,
            "all_active_scanned": self.all_active_scanned,
            "all_eligible_historical_scanned": self.all_eligible_historical_scanned,
            "truncated": self.truncated,
            "retrieval_error": self.retrieval_error,
            "reason_codes": list(self.reason_codes),
        }


@dataclass
class RetrievalResult:
    """候选召回结果：按 Claim 分组的 Revision ID 与代码计算的上下文。"""

    current_by_claim: dict[str, list[str]] = field(default_factory=dict)
    historical_by_claim: dict[str, list[str]] = field(default_factory=dict)
    current_revision_ids: list[str] = field(default_factory=list)
    historical_revision_ids: list[str] = field(default_factory=list)
    context: RetrievalContext = field(default_factory=RetrievalContext)


def retrieve_memory_candidates(
    session: Session,
    claims: list[dict],
) -> RetrievalResult:
    """按 entity / topic 规则召回候选 Memory 的当前 Revision。

    只有 change_signal 非 none 的 Claim 才触发 obsolete 历史召回；
    obsolete 候选只用于 updates 解释，不参与普通 duplicate 已知聚合。
    """

    result = RetrievalResult()
    if not claims:
        result.context.reason_codes = ["no_active_memory"]
        return result

    try:
        rows = session.execute(
            select(CognitiveMemory, CognitiveMemoryRevision)
            .join(
                CognitiveMemoryRevision,
                CognitiveMemoryRevision.id == CognitiveMemory.current_revision_id,
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 - 召回失败必须可降级而不是中断分析
        result.context.retrieval_error = str(exc)
        result.context.reason_codes = ["retrieval_error"]
        result.context.status = "insufficient"
        return result

    active_revisions = [
        (memory, revision)
        for memory, revision in rows
        if revision.lifecycle == "active"
    ]
    obsolete_revisions = [
        (memory, revision)
        for memory, revision in rows
        if revision.lifecycle == "obsolete"
    ]
    context = result.context
    context.total_active_revision_count = len(active_revisions)
    context.total_obsolete_revision_count = len(obsolete_revisions)
    context.all_active_scanned = len(active_revisions) <= FULL_SCAN_THRESHOLD

    current_ids: set[str] = set()
    historical_ids: set[str] = set()
    claim_has_current: dict[str, bool] = {}
    claim_has_historical: dict[str, bool] = {}
    historical_triggered = False

    for claim in claims:
        entities = {item for item in claim.get("entities") or [] if item}
        topics = {item for item in claim.get("topics") or [] if item}
        change_signal = claim.get("change_signal") or "none"

        claim_current: list[str] = []
        claim_historical: list[str] = []
        if entities or topics or context.all_active_scanned:
            for memory, revision in active_revisions:
                if not (entities or topics):
                    break
                matched = False
                if entities and set(revision.entities_json) & entities:
                    context.entity_match_count += 1
                    matched = True
                elif topics and set(revision.topics_json) & topics:
                    context.topic_match_count += 1
                    matched = True
                if matched:
                    claim_current.append(revision.id)
        # Memory 数量很小时允许在上下文预算内传递全部 current Revision。
        if context.all_active_scanned and (not entities and not topics):
            claim_current = [revision.id for _memory, revision in active_revisions]
        claim_has_current[claim.get("claim_id")] = bool(claim_current)

        if change_signal != "none":
            historical_triggered = True
            eligible = [
                (memory, revision)
                for memory, revision in obsolete_revisions
                if (entities and set(revision.entities_json) & entities)
                or (topics and set(revision.topics_json) & topics)
                or (not entities and not topics)
            ]
            context.all_eligible_historical_scanned = (
                len(obsolete_revisions) <= FULL_SCAN_THRESHOLD
            )
            claim_historical = [revision.id for _memory, revision in eligible]
            claim_has_historical[claim.get("claim_id")] = bool(claim_historical)
            historical_ids.update(claim_historical)

        result.current_by_claim[claim.get("claim_id")] = claim_current
        result.historical_by_claim[claim.get("claim_id")] = claim_historical
        current_ids.update(claim_current)

    context.historical_recall_triggered = historical_triggered
    if historical_triggered and not result.historical_by_claim:
        context.all_eligible_historical_scanned = (
            len(obsolete_revisions) <= FULL_SCAN_THRESHOLD
        )

    # 候选超预算时按添加顺序截断；截断后该 Claim 视为未获得完整候选。
    ordered_current = sorted(current_ids)
    ordered_historical = sorted(historical_ids)
    if len(ordered_current) + len(ordered_historical) > MAX_CANDIDATES:
        context.truncated = True
        context.reason_codes.append("candidate_truncated")
        ordered_current = ordered_current[: MAX_CANDIDATES - len(ordered_historical)]
    result.current_revision_ids = ordered_current
    result.historical_revision_ids = ordered_historical
    context.current_candidate_count = len(ordered_current)
    context.historical_candidate_count = len(ordered_historical)
    context.candidate_count = context.current_candidate_count + context.historical_candidate_count

    _assign_status(context, claim_has_current, claim_has_historical, historical_triggered)
    return result


def _assign_status(
    context: RetrievalContext,
    claim_has_current: dict[str, bool],
    claim_has_historical: dict[str, bool],
    historical_triggered: bool,
) -> None:
    """按 8.2 操作定义计算 sufficient / partial / insufficient。"""

    if context.retrieval_error:
        context.status = "insufficient"
        return
    if context.total_active_revision_count == 0 and context.total_obsolete_revision_count == 0:
        context.status = "insufficient"
        if "no_active_memory" not in context.reason_codes:
            context.reason_codes.append("no_active_memory")
        return

    if not context.reason_codes:
        context.reason_codes = ["rule_complete"]
    if context.truncated:
        context.status = "partial"
        return
    if historical_triggered and not context.all_eligible_historical_scanned:
        context.status = "partial"
        return
    unmatched = [
        claim_id
        for claim_id, has_current in claim_has_current.items()
        if not has_current and not context.all_active_scanned
    ]
    if unmatched:
        context.status = "partial"
        if "unmatched_claim_without_full_scan" not in context.reason_codes:
            context.reason_codes.append("unmatched_claim_without_full_scan")
        return
    if context.candidate_count == 0 and context.total_active_revision_count > 0:
        # 有 active Memory 但没有任何 Claim 匹配且未全量扫描：上下文不足。
        context.status = "partial"
        return
    context.status = "sufficient"
