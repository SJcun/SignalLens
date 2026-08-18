"""Cognitive Memory 服务：匹配、创建、修订与确认。

Memory 具体内容只存在于 append-only Revision 中；CREATE 前必须先执行
Memory Match，等价且状态未变时只追加 Confirmation Event。LLM 只输出
结构化判断，不能直接写入 Memory；所有 Revision ID 都必须来自本次匹配
实际检查过的候选集合。
"""

import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .analysis.pipeline import StructuredOutputProvider
from .models import (
    CognitiveMemory,
    CognitiveMemoryEvidence,
    CognitiveMemoryRevision,
    ContentClaim,
    MemoryChangeProposal,
    MemoryConfirmationEvent,
    utc_now,
)

MEMORY_MATCH_PROMPT_VERSION = "v0.1.0"

MEMORY_MATCH_SYSTEM_PROMPT = """你是 SignalLens 的认知记忆匹配器。
判断一条待记录的用户认知与给定候选认知记忆是否等价。
等价指表达同一核心认知；只在候选表达确实包含该认知时才选 equivalent。
用户立场（认同或反对）不影响等价判断；新旧版本替代属于不同认知，不算等价。
只从给定候选中选择匹配项，不得编造 ID。不确定时选择 uncertain。"""

# 单次语义判断的候选上限，避免超出模型上下文预算。
MAX_MATCH_CANDIDATES = 8


class MemoryMatchJudgment(BaseModel):
    """LLM 对候选 Memory 与待写入认知是否等价的判断。"""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["equivalent", "different", "uncertain"]
    # equivalent 时必须指向实际检查过的候选 Revision 及其逻辑 Memory。
    matched_memory_id: str | None = None
    matched_memory_revision_id: str | None = None
    confidence: Literal["high", "medium", "low"]
    reason: str = Field(min_length=1, max_length=400)


@dataclass
class MemoryMatchResult:
    """应用层组装并校验后的匹配结果，LLM 不能独立决定这些字段。"""

    decision: Literal["equivalent", "different", "uncertain"]
    matched_memory_id: str | None
    matched_memory_revision_id: str | None
    candidate_memory_revision_ids: list[str] = field(default_factory=list)
    # exact_text / cognitive_delta / entity_topic / none
    match_source: str = "none"
    reason: str = ""
    confidence: Literal["high", "medium", "low"] = "low"


class MemoryRevisionConflict(RuntimeError):
    """expected current revision 与当前指针不一致时抛出的冲突。"""


class MemoryProposalError(RuntimeError):
    """Proposal 状态或引用不满足接受条件时抛出的错误。"""


def _normalize_text(text: str) -> str:
    """去除空白与标点后统一小写，用于确定性完全匹配。"""

    return "".join(
        char.lower()
        for char in text
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _recall_candidates(
    session: Session,
    statement: str,
    topics: list[str],
    entities: list[str],
    include_obsolete: bool = False,
) -> list[tuple[CognitiveMemory, CognitiveMemoryRevision, str]]:
    """按实体优先、主题次之召回候选 Memory 的 current Revision。

    返回 (memory, revision, match_source) 列表；实体或主题为空时按
    最近使用时间补充少量候选，保证空画像阶段也能执行语义匹配。
    """

    rows = session.execute(
        select(CognitiveMemory, CognitiveMemoryRevision)
        .join(
            CognitiveMemoryRevision,
            CognitiveMemoryRevision.id == CognitiveMemory.current_revision_id,
        )
        .where(
            CognitiveMemoryRevision.lifecycle == "active"
            if not include_obsolete
            else CognitiveMemoryRevision.lifecycle.in_(["active", "obsolete"])
        )
        .order_by(CognitiveMemoryRevision.created_at.desc())
    ).all()
    entity_hits: list[tuple[CognitiveMemory, CognitiveMemoryRevision, str]] = []
    topic_hits: list[tuple[CognitiveMemory, CognitiveMemoryRevision, str]] = []
    others: list[tuple[CognitiveMemory, CognitiveMemoryRevision, str]] = []
    for memory, revision in rows:
        revision_entities = set(revision.entities_json)
        revision_topics = set(revision.topics_json)
        if entities and revision_entities & set(entities):
            entity_hits.append((memory, revision, "entity_topic"))
        elif topics and revision_topics & set(topics):
            topic_hits.append((memory, revision, "entity_topic"))
        else:
            others.append((memory, revision, "entity_topic"))
    candidates = entity_hits + topic_hits
    if not candidates:
        candidates = others
    return candidates[:MAX_MATCH_CANDIDATES]


def run_memory_match(
    session: Session,
    provider: StructuredOutputProvider | None,
    *,
    statement: str,
    claim_id: str | None = None,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
    delta_matches: list[str] | None = None,
) -> MemoryMatchResult:
    """执行 CREATE 前 Memory Match，返回应用层校验过的匹配结果。

    匹配顺序：规范化文本完全匹配 → 复用当前 Cognitive Delta 的 matches
    → 按 entity / topic 召回 → LLM 语义判断。只有确定性完全匹配或通过
    Schema 校验且 confidence = high 的语义判断才自动采用；其余降级
    uncertain，由调用方生成待确认 Proposal。
    """

    statement = (statement or "").strip()
    normalized = _normalize_text(statement)

    exact_matches = session.execute(
        select(CognitiveMemory, CognitiveMemoryRevision)
        .join(
            CognitiveMemoryRevision,
            CognitiveMemoryRevision.id == CognitiveMemory.current_revision_id,
        )
        .where(CognitiveMemoryRevision.lifecycle == "active")
    ).all()
    for memory, revision in exact_matches:
        if _normalize_text(revision.statement) == normalized:
            return MemoryMatchResult(
                decision="equivalent",
                matched_memory_id=memory.id,
                matched_memory_revision_id=revision.id,
                candidate_memory_revision_ids=[revision.id],
                match_source="exact_text",
                reason="规范化文本完全匹配",
                confidence="high",
            )

    candidate_pairs: list[tuple[CognitiveMemory, CognitiveMemoryRevision, str]] = []
    matched_sources: set[str] = set()
    if delta_matches:
        for revision_id in delta_matches:
            memory, revision = _load_revision_pair(session, revision_id)
            if memory is not None and revision is not None:
                candidate_pairs.append((memory, revision, "cognitive_delta"))
                matched_sources.add("cognitive_delta")
    if not candidate_pairs:
        candidate_pairs = _recall_candidates(
            session,
            statement,
            list(topics or []),
            list(entities or []),
        )
        if candidate_pairs:
            matched_sources.add("entity_topic")
    match_source = (
        "cognitive_delta" if "cognitive_delta" in matched_sources else "entity_topic"
    )

    if not candidate_pairs:
        # 召回流程正常但没有已确认候选：视为"相对已记录认知无对应项"，
        # 不调用 LLM，也绝不断言用户现实中绝对不知道。
        return MemoryMatchResult(
            decision="different",
            matched_memory_id=None,
            matched_memory_revision_id=None,
            candidate_memory_revision_ids=[],
            match_source="none",
            reason="没有可匹配的已确认认知记忆",
            confidence="medium",
        )

    if provider is None:
        return MemoryMatchResult(
            decision="uncertain",
            matched_memory_id=None,
            matched_memory_revision_id=None,
            candidate_memory_revision_ids=[item[1].id for item in candidate_pairs],
            match_source=match_source,
            reason="未配置 LLM，无法完成语义等价判断",
            confidence="low",
        )

    candidates = [
        {
            "memory_id": memory.id,
            "revision_id": revision.id,
            "statement": revision.statement,
            "awareness_state": revision.awareness_state,
            "stance": revision.stance,
            "lifecycle": revision.lifecycle,
            "version": revision.version,
        }
        for memory, revision, _source in candidate_pairs
    ]
    from .analysis.prompts import _json_text

    try:
        judgment = provider.complete(
            system_prompt=MEMORY_MATCH_SYSTEM_PROMPT,
            user_prompt=_json_text(
                {
                    "incoming_statement": statement,
                    "claim_id": claim_id,
                    "candidate_revisions": candidates,
                }
            ),
            output_model=MemoryMatchJudgment,
        )
    except Exception as exc:  # noqa: BLE001 - 模型失败统一降级为 uncertain，不冒险合并或新建。
        return MemoryMatchResult(
            decision="uncertain",
            matched_memory_id=None,
            matched_memory_revision_id=None,
            candidate_memory_revision_ids=[item[1].id for item in candidate_pairs],
            match_source=match_source,
            reason=f"语义匹配调用失败：{exc}",
            confidence="low",
        )

    checked_revision_ids = {item[1].id for item in candidate_pairs}
    matched_revision_id = judgment.matched_memory_revision_id
    matched_memory_id = judgment.matched_memory_id
    valid_match = (
        matched_revision_id in checked_revision_ids
        and matched_memory_id in {item[0].id for item in candidate_pairs}
        and matched_memory_id
        == next((memory.id for memory, revision, _ in candidate_pairs if revision.id == matched_revision_id), None)
    )
    if judgment.decision == "equivalent":
        if not valid_match:
            return MemoryMatchResult(
                decision="uncertain",
                matched_memory_id=None,
                matched_memory_revision_id=None,
                candidate_memory_revision_ids=sorted(checked_revision_ids),
                match_source=match_source,
                reason="语义判断引用了本次未检查的 Revision",
                confidence="low",
            )
        if judgment.confidence != "high":
            return MemoryMatchResult(
                decision="uncertain",
                matched_memory_id=None,
                matched_memory_revision_id=None,
                candidate_memory_revision_ids=sorted(checked_revision_ids),
                match_source=match_source,
                reason=f"等价判断置信不足（{judgment.confidence}）",
                confidence="low",
            )
        return MemoryMatchResult(
            decision="equivalent",
            matched_memory_id=matched_memory_id,
            matched_memory_revision_id=matched_revision_id,
            candidate_memory_revision_ids=sorted(checked_revision_ids),
            match_source=match_source,
            reason=judgment.reason,
            confidence=judgment.confidence,
        )
    if judgment.decision == "different":
        if judgment.matched_memory_id is not None or judgment.matched_memory_revision_id is not None:
            return MemoryMatchResult(
                decision="uncertain",
                matched_memory_id=None,
                matched_memory_revision_id=None,
                candidate_memory_revision_ids=sorted(checked_revision_ids),
                match_source=match_source,
                reason="different 判断不得携带匹配 ID",
                confidence="low",
            )
        if judgment.confidence != "high":
            return MemoryMatchResult(
                decision="uncertain",
                matched_memory_id=None,
                matched_memory_revision_id=None,
                candidate_memory_revision_ids=sorted(checked_revision_ids),
                match_source=match_source,
                reason=f"不同判断置信不足（{judgment.confidence}）",
                confidence="low",
            )
        return MemoryMatchResult(
            decision="different",
            matched_memory_id=None,
            matched_memory_revision_id=None,
            candidate_memory_revision_ids=sorted(checked_revision_ids),
            match_source=match_source,
            reason=judgment.reason,
            confidence=judgment.confidence,
        )
    return MemoryMatchResult(
        decision="uncertain",
        matched_memory_id=None,
        matched_memory_revision_id=None,
        candidate_memory_revision_ids=sorted(checked_revision_ids),
        match_source=match_source,
        reason=judgment.reason,
        confidence=judgment.confidence,
    )


def _load_revision_pair(
    session: Session, revision_id: str
) -> tuple[CognitiveMemory | None, CognitiveMemoryRevision | None]:
    """按 Revision ID 读取其逻辑 Memory 与当前指针状态。"""

    memory = session.scalar(
        select(CognitiveMemory).where(CognitiveMemory.current_revision_id == revision_id)
    )
    revision = session.get(CognitiveMemoryRevision, revision_id)
    return memory, revision


def create_memory(
    session: Session,
    *,
    statement: str,
    awareness_state: str,
    stance: str,
    lifecycle: str = "active",
    confidence: str = "medium",
    source_type: str,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
    content_claim_id: str | None = None,
    evidence_role: str = "origin",
    confirmed_at=None,
) -> tuple[CognitiveMemory, CognitiveMemoryRevision]:
    """创建新的逻辑 Memory 与其 Version 1 Revision。"""

    memory = CognitiveMemory()
    session.add(memory)
    session.flush()
    revision = CognitiveMemoryRevision(
        cognitive_memory_id=memory.id,
        version=1,
        statement=statement.strip(),
        awareness_state=awareness_state,
        stance=stance,
        lifecycle=lifecycle,
        confidence=confidence,
        topics_json=list(topics or []),
        entities_json=list(entities or []),
        source_type=source_type,
        confirmed_at=confirmed_at or utc_now(),
    )
    session.add(revision)
    session.flush()
    memory.current_revision_id = revision.id
    _add_evidence(
        session,
        revision.id,
        content_claim_id=content_claim_id,
        evidence_role=evidence_role,
    )
    return memory, revision


def append_memory_revision(
    session: Session,
    memory_id: str,
    *,
    statement: str,
    awareness_state: str,
    stance: str,
    lifecycle: str = "active",
    confidence: str = "medium",
    source_type: str,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
    expected_current_revision_id: str | None = None,
    content_claim_id: str | None = None,
    evidence_role: str = "origin",
    confirmed_at=None,
) -> CognitiveMemoryRevision:
    """为已有 Memory 追加不可变 Revision 并原子更新当前指针。

    expected_current_revision_id 与当前指针不一致时抛冲突，防止覆盖
    较新的用户修改。
    """

    memory = session.get(CognitiveMemory, memory_id)
    if memory is None:
        raise MemoryRevisionConflict("认知记忆不存在")
    if (
        expected_current_revision_id is not None
        and memory.current_revision_id != expected_current_revision_id
    ):
        raise MemoryRevisionConflict(
            "当前版本已变化，请基于最新版本重新确认",
        )
    max_version = (
        session.scalar(
            select(func.max(CognitiveMemoryRevision.version)).where(
                CognitiveMemoryRevision.cognitive_memory_id == memory.id
            )
        )
        or 0
    )
    revision = CognitiveMemoryRevision(
        cognitive_memory_id=memory.id,
        version=max_version + 1,
        statement=statement.strip(),
        awareness_state=awareness_state,
        stance=stance,
        lifecycle=lifecycle,
        confidence=confidence,
        topics_json=list(topics or []),
        entities_json=list(entities or []),
        source_type=source_type,
        confirmed_at=confirmed_at or utc_now(),
    )
    session.add(revision)
    session.flush()
    memory.current_revision_id = revision.id
    _add_evidence(
        session,
        revision.id,
        content_claim_id=content_claim_id,
        evidence_role=evidence_role,
    )
    return revision


def _add_evidence(
    session: Session,
    revision_id: str,
    *,
    content_claim_id: str | None,
    evidence_role: str,
) -> None:
    """为 Revision 添加来源 Claim 关联；无来源时跳过。"""

    if not content_claim_id:
        return
    existing = session.scalar(
        select(CognitiveMemoryEvidence).where(
            CognitiveMemoryEvidence.cognitive_memory_revision_id == revision_id,
            CognitiveMemoryEvidence.content_claim_id == content_claim_id,
            CognitiveMemoryEvidence.evidence_role == evidence_role,
        )
    )
    if existing is None:
        session.add(
            CognitiveMemoryEvidence(
                cognitive_memory_revision_id=revision_id,
                content_claim_id=content_claim_id,
                evidence_role=evidence_role,
            )
        )


def _add_confirmation(
    session: Session,
    memory_id: str,
    *,
    observed_revision_id: str | None,
    source_type: str,
    content_claim_id: str | None = None,
    source_feedback_id: str | None = None,
    source_proposal_id: str | None = None,
    confirmation_type: str,
) -> MemoryConfirmationEvent:
    """追加一条 append-only 的用户确认记录。"""

    event = MemoryConfirmationEvent(
        cognitive_memory_id=memory_id,
        observed_revision_id=observed_revision_id,
        source_type=source_type,
        content_claim_id=content_claim_id,
        source_feedback_id=source_feedback_id,
        source_proposal_id=source_proposal_id,
        confirmation_type=confirmation_type,
    )
    session.add(event)
    return event


def apply_memory_match(
    session: Session,
    match: MemoryMatchResult,
    *,
    statement: str,
    target_awareness: str,
    target_stance: str | None,
    target_lifecycle: str = "active",
    source_type: str,
    content_claim_id: str | None = None,
    evidence_role: str = "origin",
    confirmation_type: str = "awareness_confirmed",
    source_feedback_id: str | None = None,
    source_proposal_id: str | None = None,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
) -> tuple[str, str | None, str | None]:
    """按 Match 结果执行 6.4 处理：确认、修订、新建或生成 Proposal。

    返回 (outcome, memory_id, proposal_id)：outcome 为 confirmed / revised /
    created / proposal；memory_id 在有对应 Memory 时返回，proposal 场景
    返回新建的 Proposal ID。target_stance 为 None 表示不改变已有立场，
    新建 Memory 时默认 not_applicable。
    """

    if match.decision == "equivalent":
        memory = session.get(CognitiveMemory, match.matched_memory_id)
        revision = session.get(CognitiveMemoryRevision, match.matched_memory_revision_id)
        if memory is None or revision is None:
            raise MemoryRevisionConflict("匹配到的认知记忆已不存在")
        if memory.current_revision_id != match.matched_memory_revision_id:
            # 当前指针已变化：不能静默覆盖，转入待确认 Proposal。
            return _uncertain_proposal(
                session,
                match=match,
                statement=statement,
                target_awareness=target_awareness,
                target_stance=target_stance or revision.stance,
                target_lifecycle=target_lifecycle,
                content_claim_id=content_claim_id,
                reason="匹配时看到的版本已变化，需要用户重新确认",
            )
        changed = (
            target_awareness != revision.awareness_state
            or (target_stance is not None and target_stance != revision.stance)
            or target_lifecycle != revision.lifecycle
            or statement.strip() != revision.statement.strip()
        )
        if not changed:
            _add_confirmation(
                session,
                memory.id,
                observed_revision_id=revision.id,
                source_type=source_type,
                content_claim_id=content_claim_id,
                source_feedback_id=source_feedback_id,
                source_proposal_id=source_proposal_id,
                confirmation_type=confirmation_type,
            )
            _add_evidence(
                session,
                revision.id,
                content_claim_id=content_claim_id,
                evidence_role=evidence_role,
            )
            return "confirmed", memory.id, None
        append_memory_revision(
            session,
            memory.id,
            statement=statement,
            awareness_state=target_awareness,
            stance=target_stance or revision.stance,
            lifecycle=target_lifecycle,
            source_type=source_type,
            topics=topics,
            entities=entities,
            expected_current_revision_id=memory.current_revision_id,
            content_claim_id=content_claim_id,
            evidence_role=evidence_role,
        )
        _add_confirmation(
            session,
            memory.id,
            observed_revision_id=memory.current_revision_id,
            source_type=source_type,
            content_claim_id=content_claim_id,
            source_feedback_id=source_feedback_id,
            source_proposal_id=source_proposal_id,
            confirmation_type=confirmation_type,
        )
        return "revised", memory.id, None

    if match.decision == "different":
        memory, revision = create_memory(
            session,
            statement=statement,
            awareness_state=target_awareness,
            stance=target_stance or "not_applicable",
            lifecycle=target_lifecycle,
            source_type=source_type,
            topics=topics,
            entities=entities,
            content_claim_id=content_claim_id,
            evidence_role=evidence_role,
        )
        _add_confirmation(
            session,
            memory.id,
            observed_revision_id=revision.id,
            source_type=source_type,
            content_claim_id=content_claim_id,
            source_feedback_id=source_feedback_id,
            source_proposal_id=source_proposal_id,
            confirmation_type=confirmation_type,
        )
        return "created", memory.id, None

    return _uncertain_proposal(
        session,
        match=match,
        statement=statement,
        target_awareness=target_awareness,
        target_stance=target_stance,
        target_lifecycle=target_lifecycle,
        content_claim_id=content_claim_id,
        reason=match.reason,
    )


def _uncertain_proposal(
    session: Session,
    *,
    match: MemoryMatchResult,
    statement: str,
    target_awareness: str,
    target_stance: str,
    target_lifecycle: str,
    content_claim_id: str | None,
    reason: str,
) -> tuple[str, None, str]:
    """匹配不确定时生成 RESOLVE_MATCH Proposal，等待用户选择。"""

    proposal = MemoryChangeProposal(
        action="RESOLVE_MATCH",
        target_memory_id=None,
        expected_current_revision_id=None,
        candidate_memory_revision_ids_json=list(match.candidate_memory_revision_ids),
        proposed_statement=statement.strip(),
        proposed_awareness_state=target_awareness,
        proposed_stance=target_stance,
        proposed_lifecycle=target_lifecycle,
        evidence_claim_ids_json=[content_claim_id] if content_claim_id else [],
        reason=reason,
        status="pending",
    )
    session.add(proposal)
    session.flush()
    return "proposal", None, proposal.id


def apply_claim_feedback(
    session: Session,
    provider: StructuredOutputProvider | None,
    *,
    content_claim_id: str,
    awareness: Literal["known", "uncertain"] | None = None,
    stance: Literal["accept", "reject", "mixed", "undecided", "not_applicable"] | None = None,
    source_feedback_id: str | None = None,
    confirmation_type: str | None = None,
) -> tuple[str, str | None, str | None, MemoryMatchResult | None]:
    """处理用户对具体 Claim 的直接确认（11.2）。

    用户明确选择立场说明已接触并理解到足以表态，此时没有 awareness
    输入也按 known 记录；目标状态先形成，再进入 Memory Match。
    """

    claim = session.get(ContentClaim, content_claim_id)
    if claim is None:
        raise MemoryRevisionConflict("Claim 不存在")
    target_awareness = awareness or ("known" if stance is not None else "uncertain")
    target_stance = stance
    if confirmation_type is not None:
        resolved_confirmation_type = confirmation_type
    elif awareness is None and stance is not None:
        resolved_confirmation_type = "stance_confirmed"
    elif awareness == "uncertain":
        resolved_confirmation_type = "awareness_confirmed"
    else:
        resolved_confirmation_type = "already_known"
    match = run_memory_match(
        session,
        provider,
        statement=claim.statement,
        claim_id=claim.claim_id,
        topics=list(claim.topics_json),
        entities=list(claim.entities_json),
    )
    outcome, memory_id, proposal_id = apply_memory_match(
        session,
        match,
        statement=claim.statement,
        target_awareness=target_awareness,
        target_stance=target_stance,
        source_type="claim_feedback",
        content_claim_id=claim.id,
        evidence_role="origin",
        confirmation_type=resolved_confirmation_type,
        source_feedback_id=source_feedback_id,
        topics=list(claim.topics_json),
        entities=list(claim.entities_json),
    )
    return outcome, memory_id, proposal_id, match


def apply_proposal_decision(
    session: Session,
    provider: StructuredOutputProvider | None,
    *,
    proposal_id: str,
    decision: Literal["accepted", "rejected"],
    merge_memory_id: str | None = None,
) -> tuple[MemoryChangeProposal, str, str | None]:
    """接受或拒绝 Memory Change Proposal；只有 accepted 才改变正式状态。

    接受前校验 expected current revision；指针已变化时标记 stale 并抛
    冲突。CREATE 与 RESOLVE_MATCH 仍需遵守 6.4：可创建、追加 Revision
    或只追加 Confirmation Event，不能绕过匹配直接写入。
    """

    proposal = session.get(MemoryChangeProposal, proposal_id)
    if proposal is None:
        raise MemoryProposalError("修改建议不存在")
    if proposal.status != "pending":
        raise MemoryProposalError(f"修改建议已处理（{proposal.status}）")

    if decision == "rejected":
        proposal.status = "rejected"
        proposal.decided_at = utc_now()
        return proposal, "rejected", None

    target_memory = None
    if proposal.target_memory_id is not None:
        target_memory = session.get(CognitiveMemory, proposal.target_memory_id)
        if target_memory is None:
            raise MemoryProposalError("目标认知记忆不存在")
        if (
            proposal.expected_current_revision_id is not None
            and target_memory.current_revision_id != proposal.expected_current_revision_id
        ):
            proposal.status = "stale"
            proposal.decided_at = utc_now()
            raise MemoryRevisionConflict("当前版本已变化，建议已过期")
    if merge_memory_id is not None and proposal.action == "RESOLVE_MATCH":
        target_memory = session.get(CognitiveMemory, merge_memory_id)
        if target_memory is None:
            raise MemoryProposalError("合并目标不存在")
        if (
            proposal.candidate_memory_revision_ids_json
            and target_memory.current_revision_id not in proposal.candidate_memory_revision_ids_json
        ):
            proposal.status = "stale"
            proposal.decided_at = utc_now()
            raise MemoryRevisionConflict("合并目标已不是当时看到的候选版本")

    statement = proposal.proposed_statement or ""
    awareness = proposal.proposed_awareness_state or "uncertain"
    stance = proposal.proposed_stance or "not_applicable"
    lifecycle = proposal.proposed_lifecycle or "active"

    if proposal.action in {"REVISE", "MARK_OBSOLETE", "REACTIVATE"}:
        if target_memory is None:
            raise MemoryProposalError("缺少目标认知记忆")
        append_memory_revision(
            session,
            target_memory.id,
            statement=statement,
            awareness_state=awareness,
            stance=stance,
            lifecycle=lifecycle,
            source_type="accepted_proposal",
            expected_current_revision_id=target_memory.current_revision_id,
            content_claim_id=proposal.evidence_claim_ids_json[0]
            if proposal.evidence_claim_ids_json
            else None,
        )
        _add_confirmation(
            session,
            target_memory.id,
            observed_revision_id=target_memory.current_revision_id,
            source_type="accepted_proposal",
            source_proposal_id=proposal.id,
            confirmation_type="awareness_confirmed",
        )
        proposal.status = "accepted"
        proposal.decided_at = utc_now()
        return proposal, "revised", target_memory.id

    if proposal.action == "RESOLVE_MATCH":
        if merge_memory_id is not None:
            if target_memory is None:
                raise MemoryProposalError("合并目标不存在")
            append_memory_revision(
                session,
                target_memory.id,
                statement=statement,
                awareness_state=awareness,
                stance=stance,
                lifecycle=lifecycle,
                source_type="accepted_proposal",
                expected_current_revision_id=target_memory.current_revision_id,
                content_claim_id=proposal.evidence_claim_ids_json[0]
                if proposal.evidence_claim_ids_json
                else None,
            )
            _add_confirmation(
                session,
                target_memory.id,
                observed_revision_id=target_memory.current_revision_id,
                source_type="accepted_proposal",
                source_proposal_id=proposal.id,
                confirmation_type="awareness_confirmed",
            )
            proposal.status = "accepted"
            proposal.decided_at = utc_now()
            return proposal, "revised", target_memory.id
        # 用户选择仍然创建新项：执行完整 Memory Match 后再落库。
        match = run_memory_match(
            session,
            provider,
            statement=statement,
            claim_id=None,
        )
        if match.decision == "uncertain":
            proposal.status = "stale"
            proposal.decided_at = utc_now()
            raise MemoryRevisionConflict("匹配仍不确定，请重新确认")
        outcome, memory_id, _proposal_id = apply_memory_match(
            session,
            match,
            statement=statement,
            target_awareness=awareness,
            target_stance=stance,
            target_lifecycle=lifecycle,
            source_type="accepted_proposal",
            content_claim_id=proposal.evidence_claim_ids_json[0]
            if proposal.evidence_claim_ids_json
            else None,
            source_proposal_id=proposal.id,
        )
        proposal.status = "accepted"
        proposal.decided_at = utc_now()
        return proposal, outcome, memory_id

    # action == CREATE：接受时也必须先执行 Memory Match。
    match = run_memory_match(
        session,
        provider,
        statement=statement,
        claim_id=None,
    )
    if match.decision == "uncertain":
        proposal.status = "stale"
        proposal.decided_at = utc_now()
        raise MemoryRevisionConflict("匹配仍不确定，请重新确认")
    outcome, memory_id, _proposal_id = apply_memory_match(
        session,
        match,
        statement=statement,
        target_awareness=awareness,
        target_stance=stance,
        target_lifecycle=lifecycle,
        source_type="accepted_proposal",
        content_claim_id=proposal.evidence_claim_ids_json[0]
        if proposal.evidence_claim_ids_json
        else None,
        source_proposal_id=proposal.id,
    )
    proposal.status = "accepted"
    proposal.decided_at = utc_now()
    return proposal, outcome, memory_id
