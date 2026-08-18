"""Claims 行级持久化与旧分析兼容。

系统在持久化阶段为每条 Claim 分配分析内稳定的 claim_id（如 claim-001），
模型输出本身不携带数据库身份；同一分析重复运行时保持已有 ID。
旧格式 Claims（升级前保存）通过补缺省字段继续可读，不参与正式 Compare。
"""

from sqlalchemy import func, select

from ..models import Analysis, ContentClaim, ContentRevision, utc_now

# 旧格式 Claims 缺少新字段时使用的保守默认值：旧主张不声明角色和类型，
# 一律按边缘细节处理，避免假装拥有可靠的核心判断。
LEGACY_CLAIM_TYPE = "interpretation"
LEGACY_CLAIM_ROLE = "detail"
LEGACY_CHANGE_SIGNAL = "none"


def with_normalized_claims(payload: dict | None) -> dict | None:
    """为旧格式 Claims 补齐缺省字段，使旧分析可以被新 Schema 解析。

    新格式数据原样返回；Web 详情与 Worker 继续旧任务时都调用本函数，
    保证升级前的已完成分析仍可展示、仍可继续后续阶段。
    """

    if not isinstance(payload, dict):
        return payload
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return payload
    normalized: list[dict] = []
    for item in claims:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        copy = dict(item)
        copy.setdefault("claim_id", None)
        copy.setdefault("claim_type", LEGACY_CLAIM_TYPE)
        copy.setdefault("claim_role", LEGACY_CLAIM_ROLE)
        copy.setdefault("change_signal", LEGACY_CHANGE_SIGNAL)
        copy.setdefault("section_ref", None)
        copy.setdefault("topics", [])
        copy.setdefault("entities", [])
        normalized.append(copy)
    payload["claims"] = normalized
    return payload


def _valid_section_ref(section_index_json: dict | None, section_ref: str) -> bool:
    """校验 Claim 引用必须来自系统章节清单，防止模型编造引用。"""

    if not section_index_json:
        return False
    sections = section_index_json.get("sections") or []
    return any(item.get("section_ref") == section_ref for item in sections)


def persist_claims(
    session,
    analysis_id: str,
    content_revision_id: str | None,
    model: str | None,
    prompt_version: str,
) -> None:
    """把 AnalyzeContent.claims 写入行级记录，并把稳定 claim_id 写回 JSON。

    旧 Claims 没有 claim_id 时按顺序分配；已有记录的分析重复调用时
    不会重复插入。section_ref 不在系统章节清单中的条目置空而不是伪造。
    """

    analysis = session.get(Analysis, analysis_id)
    if analysis is None or analysis.content_analysis_json is None:
        return
    payload = with_normalized_claims(dict(analysis.content_analysis_json))
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        return

    existing_ids = set(
        session.scalars(
            select(ContentClaim.claim_id).where(ContentClaim.analysis_id == analysis_id)
        ).all()
    )
    payload["claims"] = list(claims)
    rows: list[ContentClaim] = []
    changed = False
    for order, item in enumerate(claims, start=1):
        if not isinstance(item, dict):
            continue
        # 校验引用是否来自系统章节清单；无效引用在行级与 JSON 中同时置空。
        section_ref = item.get("section_ref")
        if section_ref is not None and not _valid_section_ref(
            analysis.section_index_json, section_ref
        ):
            section_ref = None
            item["section_ref"] = None
            changed = True
        claim_id = item.get("claim_id") or f"claim-{order:03d}"
        if claim_id not in existing_ids:
            rows.append(
                ContentClaim(
                    analysis_id=analysis_id,
                    content_revision_id=content_revision_id,
                    claim_id=claim_id,
                    claim_order=order,
                    statement=item.get("claim") or "",
                    claim_type=item.get("claim_type") or LEGACY_CLAIM_TYPE,
                    claim_role=item.get("claim_role") or LEGACY_CLAIM_ROLE,
                    change_signal=item.get("change_signal") or LEGACY_CHANGE_SIGNAL,
                    section_ref=section_ref,
                    evidence_json=list(item.get("evidence") or []),
                    verification=item.get("verification") or "unverified",
                    topics_json=list(item.get("topics") or []),
                    entities_json=list(item.get("entities") or []),
                    model=model,
                    prompt_version=prompt_version,
                )
            )
        if item.get("claim_id") != claim_id:
            item["claim_id"] = claim_id
            changed = True
    if rows:
        session.add_all(rows)
    if changed:
        analysis.content_analysis_json = payload


def load_claim_rows(session, analysis_id: str) -> list[ContentClaim]:
    """按输出顺序返回某次分析的行级 Claims；没有记录时返回空列表。"""

    return list(
        session.scalars(
            select(ContentClaim)
            .where(ContentClaim.analysis_id == analysis_id)
            .order_by(ContentClaim.claim_order)
        ).all()
    )


def ensure_content_revision(session, content_id: str, source_hash: str, title: str, markdown: str) -> ContentRevision:
    """按内容与正文哈希查找或创建不可变正文 Revision。"""

    revision = session.scalar(
        select(ContentRevision).where(
            ContentRevision.content_id == content_id,
            ContentRevision.source_hash == source_hash,
        )
    )
    if revision is not None:
        return revision
    max_version = (
        session.scalar(
            select(func.max(ContentRevision.version)).where(
                ContentRevision.content_id == content_id
            )
        )
        or 0
    )
    revision = ContentRevision(
        content_id=content_id,
        version=max_version + 1,
        source_hash=source_hash,
        title=title,
        markdown=markdown,
        created_at=utc_now(),
    )
    session.add(revision)
    session.flush()
    return revision
