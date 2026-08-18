"""Cognitive Compare 契约、结构校验与确定性 Delta 聚合。

Compare 只负责逐 Claim 比较新 Claims 与候选 Memory Revision，不生成
推荐、不修改 Memory；聚合统计与召回上下文状态由确定性代码生成，
LLM 只输出关系，避免重复计数或 Schema 自相矛盾。
"""

from typing import Literal

from pydantic import Field

from .schemas import CompactText, StrictOutputModel

PrimaryRelation = Literal[
    "duplicate", "extends", "complements", "contradicts", "updates", "new"
]
MatchRelation = Literal["duplicate", "extends", "complements", "contradicts", "updates"]


class CompareMatch(StrictOutputModel):
    """某个 Memory Revision 对当前 Claim 的一条解释关系。"""

    memory_revision_id: str
    # 候选必须来自代码分组：current 或 historical，LLM 不能更改分组。
    candidate_kind: Literal["current", "historical"]
    # new 不能作为 match 关系；`new` 只出现在 primary_relation。
    relation: MatchRelation
    reason: CompactText


class CompareRelation(StrictOutputModel):
    """当前 Claim 的主要认知关系与多 Memory 解释证据。"""

    current_claim_id: str
    primary_relation: PrimaryRelation
    # 解释证据：一个 Claim 可以匹配多个 Memory Revision，但只统计 primary。
    matches: list[CompareMatch] = Field(default_factory=list, max_length=5)
    added_information: CompactText | None = None
    # primary_relation = contradicts 时必须提供。
    conflict_summary: CompactText | None = None
    reason: CompactText
    confidence: Literal["low", "medium", "high"]


class CognitiveCompare(StrictOutputModel):
    """逐 Claim 的认知关系输出，不包含任何聚合列表。"""

    relations: list[CompareRelation] = Field(min_length=1, max_length=30)


class CompareValidationError(ValueError):
    """Compare 输出不满足结构约束时抛出的异常。"""


def validate_compare_output(
    output: CognitiveCompare,
    *,
    claim_ids: list[str],
    current_candidate_ids: list[str],
    historical_candidate_ids: list[str],
) -> None:
    """校验逐 Claim 关系与候选引用完整性，防止统计错位。

    约束：
    - current_claim_id 集合必须与输入 Claim ID 集合完全相同且无重复；
    - matches 引用的 Revision 必须来自本次 current 或 historical 候选；
    - candidate_kind 必须与候选来源一致；
    - primary_relation = new 时 matches 必须为空；
    - 其他关系至少包含一个 match，且 primary 必须出现在某条 match 中；
    - primary_relation = contradicts 时必须提供 conflict_summary。
    """

    checked_current = set(current_candidate_ids)
    checked_historical = set(historical_candidate_ids)
    if checked_current & checked_historical:
        raise CompareValidationError("current 与 historical 候选不能重叠")

    output_ids = [item.current_claim_id for item in output.relations]
    if len(output_ids) != len(set(output_ids)):
        raise CompareValidationError("当前 Claim 在输出中重复出现")
    if set(output_ids) != set(claim_ids):
        raise CompareValidationError("当前 Claim 集合与输入不一致")

    for relation in output.relations:
        if relation.primary_relation == "new":
            if relation.matches:
                raise CompareValidationError("new 关系不得携带 match 证据")
            continue
        if not relation.matches:
            raise CompareValidationError(
                f"{relation.primary_relation} 关系必须引用 Memory Revision"
            )
        primary_kinds = []
        for match in relation.matches:
            if match.relation == "new":
                raise CompareValidationError("match 关系不能是 new")
            if match.candidate_kind == "current":
                if match.memory_revision_id not in checked_current:
                    raise CompareValidationError("引用了本次未检查的 current Revision")
                primary_kinds.append("current")
            else:
                if match.memory_revision_id not in checked_historical:
                    raise CompareValidationError("引用了本次未检查的 historical Revision")
                primary_kinds.append("historical")
        if relation.primary_relation not in {match.relation for match in relation.matches}:
            raise CompareValidationError("主关系必须与至少一条 match 关系相同")
        if relation.primary_relation == "contradicts" and not relation.conflict_summary:
            raise CompareValidationError("contradicts 关系必须提供冲突摘要")


def derive_delta_summary(
    output: CognitiveCompare,
    *,
    claims: list[dict],
    current_candidate_ids: list[str],
    historical_candidate_ids: list[str],
    current_revision_awareness: dict[str, str],
    retrieval_context: dict,
) -> dict:
    """由确定性代码计算 Delta 聚合，LLM 不参与。

    cognitive_gain 只统计 primary_relation：new / extends / complements /
    contradicts / updates；duplicate 再按 awareness_state = known 拆分
    "用户已知重复"，避免把 uncertain 或 historical 候选当成已知。
    """

    role_by_claim = {item.get("claim_id"): item.get("claim_role") for item in claims}
    relation_counts_by_role: dict[str, dict[str, int]] = {
        role: {} for role in ("core", "supporting", "detail")
    }
    duplicate_claim_ids: list[str] = []
    known_duplicate_claim_ids: list[str] = []
    uncertain_overlap_claim_ids: list[str] = []
    gain_claim_ids: list[str] = []
    gain_by_role: dict[str, list[str]] = {
        "core": [],
        "supporting": [],
        "detail": [],
    }
    used_revision_ids: set[str] = set()

    for relation in output.relations:
        role = role_by_claim.get(relation.current_claim_id, "detail")
        bucket = relation_counts_by_role.setdefault(role, {})
        bucket[relation.primary_relation] = bucket.get(relation.primary_relation, 0) + 1
        for match in relation.matches:
            used_revision_ids.add(match.memory_revision_id)

        if relation.primary_relation == "duplicate":
            duplicate_claim_ids.append(relation.current_claim_id)
            known_match = any(
                match.candidate_kind == "current"
                and match.relation == "duplicate"
                and current_revision_awareness.get(match.memory_revision_id) == "known"
                for match in relation.matches
            )
            if known_match:
                known_duplicate_claim_ids.append(relation.current_claim_id)
            else:
                uncertain_overlap_claim_ids.append(relation.current_claim_id)
        elif relation.primary_relation in {"new", "extends", "complements", "contradicts", "updates"}:
            gain_claim_ids.append(relation.current_claim_id)
            gain_by_role.setdefault(role, []).append(relation.current_claim_id)

    unused_candidate_ids = sorted(
        (set(current_candidate_ids) | set(historical_candidate_ids)) - used_revision_ids
    )
    return {
        "relation_counts_by_role": relation_counts_by_role,
        "duplicate_claim_ids": duplicate_claim_ids,
        "known_duplicate_claim_ids": known_duplicate_claim_ids,
        "uncertain_overlap_claim_ids": uncertain_overlap_claim_ids,
        "cognitive_gain_claim_ids": gain_claim_ids,
        "core_gain_claim_ids": gain_by_role.get("core", []),
        "supporting_gain_claim_ids": gain_by_role.get("supporting", []),
        "detail_gain_claim_ids": gain_by_role.get("detail", []),
        "unused_candidate_memory_revision_ids": unused_candidate_ids,
        "retrieval_context_status": retrieval_context.get("status"),
    }
