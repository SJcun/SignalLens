"""持久化分析任务 Worker。"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy import case, func, select, update

from .analysis.claims import (
    ensure_content_revision,
    persist_claims,
    with_normalized_claims,
)
from .analysis.compare import (
    derive_delta_summary,
    validate_compare_output,
)
from .analysis.pipeline import (
    AnalysisInput,
    StructuredOutputProvider,
    run_cognitive_compare,
    run_content_analysis,
    run_personal_evaluation,
    run_triage,
)
from .analysis.prompts import PROMPT_VERSION
from .analysis.provider import build_provider_from_settings
from .analysis.retrieval import retrieve_memory_candidates
from .analysis.schemas import (
    AnalyzeContent,
    CurrentUserState,
    EvaluateForUser,
    TriageContent,
    UserProfile,
)
from .analysis.sections import SectionIndex, build_section_index, validate_guided_flow
from .database import SessionLocal, create_schema
from .models import (
    Analysis,
    AnalysisJob,
    AnalysisSchedule,
    CognitiveCompareRun,
    CognitiveMemoryRevision,
    Content,
    ContentTranslation,
    CurrentUserStateRecord,
    CurrentUserStateSnapshot,
    UserProfileRecord,
    utc_now,
)
from .scheduling import is_within_windows
from .translation import (
    TRANSLATION_PROMPT_VERSION,
    content_source_hash,
    run_translation_batch,
    translation_batches,
)

LOGGER = logging.getLogger("signallens.worker")


@dataclass
class ClaimedAnalysisJob:
    """一次原子领取后执行当前阶段所需的持久化输入。"""

    analysis_id: str
    stage: str
    content: AnalysisInput
    triage: TriageContent | None
    content_analysis: AnalyzeContent | None
    content_revision_id: str | None


def pending_job_count() -> int:
    """返回等待处理的任务数，供启动日志和健康检查使用。"""

    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "pending")
            )
            or 0
        )


def process_next_job(
    provider: StructuredOutputProvider,
    profile: UserProfile | None = None,
) -> bool:
    """领取并处理一条任务；没有待处理任务时返回 False。"""

    claimed = _claim_next_job(provider.model)
    if claimed is None:
        return False

    analysis_id = claimed.analysis_id
    user_profile = profile or _load_user_profile()
    try:
        stage = claimed.stage
        triage = claimed.triage
        content_analysis = claimed.content_analysis
        while True:
            # 每个模型请求前都重新检查门禁；窗口关闭后保留当前阶段结果，
            # 下一窗口从后续阶段继续，避免三阶段跨越高价时段。
            if stage == "triage":
                triage = run_triage(provider, claimed.content, user_profile)
                _save_triage(analysis_id, triage)
                if triage.decision == "ignore":
                    _complete_analysis(analysis_id)
                    return True
                stage = "analyze"
            elif stage == "analyze" and triage is not None:
                content_analysis = run_content_analysis(provider, claimed.content, triage)
                _save_content_analysis(analysis_id, content_analysis)
                stage = "persist_claims"
            elif stage == "persist_claims":
                # 系统分配稳定 claim_id 并把 Claims 落为行级记录；
                # 旧分析缺少正文 Revision 时只持久化，不进入正式 Compare。
                _persist_claims(analysis_id)
                stage = "retrieve_memory"
            elif stage == "retrieve_memory":
                # 代码执行 current / historical 候选召回并计算召回上下文。
                _retrieve_memory_candidates(analysis_id)
                stage = "compare"
            elif stage == "compare":
                _run_compare_stage(provider, analysis_id)
                stage = "evaluate"
            elif stage == "evaluate" and content_analysis is not None:
                user_state = _ensure_user_state_snapshot(analysis_id)
                delta_summary = _evaluation_delta_summary(analysis_id)
                evaluation = run_personal_evaluation(
                    provider,
                    content_analysis,
                    user_profile,
                    user_state,
                    delta_summary,
                )
                _save_evaluation(analysis_id, evaluation, content_analysis)
                return True
            else:
                raise RuntimeError(f"分析任务阶段数据不完整：{analysis_id}/{stage}")

            if not _can_continue_analysis(analysis_id):
                _pause_analysis(analysis_id)
                return True
    except Exception as exc:
        # 单条模型失败不能结束 Worker；失败状态保留原因，便于后续人工重试。
        _fail_analysis(analysis_id, exc)
        LOGGER.exception("分析任务失败：%s", analysis_id)
        return True


def process_next_translation(provider: StructuredOutputProvider) -> bool:
    """领取并处理一条正文翻译任务；没有待处理任务时返回 False。"""

    claimed = _claim_next_translation(provider.model)
    if claimed is None:
        return False

    translation_id, blocks = claimed
    try:
        for batch in translation_batches(blocks):
            result = run_translation_batch(provider, batch)
            _save_translation_batch(translation_id, result)
        _complete_translation(translation_id)
        return True
    except Exception as exc:
        # 已完成的批次会保留；用户重试时只继续翻译尚未完成的块。
        _fail_translation(translation_id, exc)
        LOGGER.exception("翻译任务失败：%s", translation_id)
        return True


def _claim_next_job(model: str) -> ClaimedAnalysisJob | None:
    """使用条件更新领取最早任务，防止多个 Worker 重复消费。"""

    with SessionLocal.begin() as session:
        schedule = session.get(AnalysisSchedule, "default")
        schedule_open = (
            schedule is None
            or not schedule.enabled
            or is_within_windows(utc_now(), list(schedule.windows_json))
        )
        candidate_query = select(AnalysisJob.id).where(AnalysisJob.status == "pending")
        if not schedule_open:
            candidate_query = candidate_query.where(
                AnalysisJob.immediate_requested_at.is_not(None)
            )
        candidate_id = session.scalar(
            candidate_query.order_by(
                case(
                    (AnalysisJob.immediate_requested_at.is_not(None), 0),
                    else_=1,
                ),
                AnalysisJob.immediate_requested_at,
                AnalysisJob.created_at,
            ).limit(1)
        )
        if candidate_id is None:
            return None

        result = session.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == candidate_id, AnalysisJob.status == "pending")
            .values(status="running", attempts=AnalysisJob.attempts + 1)
        )
        if result.rowcount != 1:
            return None

        job = session.get(AnalysisJob, candidate_id)
        if job is None:
            return None
        analysis = session.get(Analysis, job.analysis_id)
        if analysis is None:
            return None
        content = session.get(Content, analysis.content_id)
        if content is None:
            return None

        analysis.status = "running"
        analysis.model = model
        analysis.prompt_version = PROMPT_VERSION
        # 章节清单必须在模型调用前建立：首次领取时解析当前正文快照。
        # 正文在分析期间被重新采集时，旧阶段结果与新正文不能混用，从头重新分析。
        source_hash = content_source_hash(content.markdown)
        if analysis.source_hash is None:
            analysis.source_hash = source_hash
            analysis.section_index_json = _section_index_json(content.markdown, content.title)
            # 首次领取的新分析固定关联当前正文 Revision，旧 Claims 有快照可追溯。
            revision = ensure_content_revision(
                session, content.id, source_hash, content.title, content.markdown
            )
            analysis.content_revision_id = revision.id
        elif analysis.source_hash != source_hash:
            analysis.source_hash = source_hash
            analysis.section_index_json = _section_index_json(content.markdown, content.title)
            analysis.triage_json = None
            analysis.content_analysis_json = None
            analysis.personal_evaluation_json = None
            analysis.completed_at = None
            revision = ensure_content_revision(
                session, content.id, source_hash, content.title, content.markdown
            )
            analysis.content_revision_id = revision.id
            job.stage = "triage"
        return ClaimedAnalysisJob(
            analysis_id=analysis.id,
            stage=job.stage,
            content=AnalysisInput(
                title=content.title,
                source_url=content.source_url,
                source_type=content.source_type,
                capture_mode=content.capture_mode,
                capture_quality=content.capture_quality,
                markdown=content.markdown,
                section_index=(
                    SectionIndex.model_validate(analysis.section_index_json)
                    if analysis.section_index_json
                    else None
                ),
            ),
            triage=(
                TriageContent.model_validate(analysis.triage_json)
                if analysis.triage_json
                else None
            ),
            content_analysis=(
                AnalyzeContent.model_validate(
                    with_normalized_claims(analysis.content_analysis_json)
                )
                if analysis.content_analysis_json
                else None
            ),
            content_revision_id=analysis.content_revision_id,
        )


def _section_index_json(markdown: str, title: str) -> dict | None:
    """解析正文主章节清单；没有合适层级时保存 None。"""

    index = build_section_index(markdown, title)
    return index.model_dump(mode="json") if index else None


def _can_continue_analysis(analysis_id: str) -> bool:
    """在下一阶段发起模型请求前重新读取总开关和当前窗口。"""

    with SessionLocal() as session:
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        if job is None:
            return False
        if job.immediate_requested_at is not None:
            return True
        schedule = session.get(AnalysisSchedule, "default")
        return (
            schedule is None
            or not schedule.enabled
            or is_within_windows(utc_now(), list(schedule.windows_json))
        )


def _pause_analysis(analysis_id: str) -> None:
    """窗口关闭时释放任务领取状态，保留已完成阶段供后续继续。"""

    with SessionLocal.begin() as session:
        _, job = _load_running_task(session, analysis_id)
        job.status = "pending"


def _claim_next_translation(model: str) -> tuple[str, list[dict]] | None:
    """原子领取最早的待翻译记录，并返回当前断点内容块。"""

    with SessionLocal.begin() as session:
        candidate_id = session.scalar(
            select(ContentTranslation.id)
            .where(ContentTranslation.status == "pending")
            .order_by(ContentTranslation.created_at)
            .limit(1)
        )
        if candidate_id is None:
            return None

        result = session.execute(
            update(ContentTranslation)
            .where(
                ContentTranslation.id == candidate_id,
                ContentTranslation.status == "pending",
            )
            .values(
                status="running",
                attempts=ContentTranslation.attempts + 1,
                model=model,
                prompt_version=TRANSLATION_PROMPT_VERSION,
            )
        )
        if result.rowcount != 1:
            return None

        translation = session.get(ContentTranslation, candidate_id)
        if translation is None:
            return None
        return translation.id, list(translation.blocks_json)


def _load_user_profile() -> UserProfile:
    """将用户显式问卷转换为模型输入；没有问卷时保持保守空画像。"""

    with SessionLocal() as session:
        record = session.get(UserProfileRecord, "default")
        if record is None or record.questionnaire_completed_at is None:
            return UserProfile()
        known_topics = [
            f"{item['topic']}（{item['level']}）"
            for item in record.known_topics_json
            if item.get("topic") and item.get("level")
        ]
        return UserProfile(
            focus_topics=record.focus_topics_json,
            known_topics=known_topics,
            reading_goals=record.reading_goals_json,
            preferred_depth=record.preferred_depth,
            time_budget_minutes=record.time_budget_minutes,
            exploration_level=record.exploration_level,
        )


def _ensure_user_state_snapshot(analysis_id: str) -> CurrentUserState:
    """Evaluate 前创建或复用不可变的 Current User State 快照。

    快照只创建一次：暂停后续跑时保持当时看到的状态，不随用户修改漂移。
    状态过期或为空时使用保守默认值，不阻止分析。
    """

    with SessionLocal.begin() as session:
        analysis = session.get(Analysis, analysis_id)
        if analysis is None:
            raise RuntimeError(f"分析任务不存在：{analysis_id}")
        if analysis.current_user_state_snapshot_id is not None:
            snapshot = session.get(
                CurrentUserStateSnapshot, analysis.current_user_state_snapshot_id
            )
            if snapshot is not None:
                return CurrentUserState.model_validate(snapshot.payload_json)

        # 快照始终保存完整字段结构；状态过期或未设置时全部使用保守默认值。
        payload = {
            "active_goals": [],
            "active_questions": [],
            "focus_context": None,
            "available_minutes": None,
            "preferred_depth": None,
            "exploration_level": None,
        }
        record = session.get(CurrentUserStateRecord, "default")
        if record is not None and not _state_expired(record.valid_until):
            payload.update(
                {
                    "active_goals": list(record.active_goals_json),
                    "active_questions": list(record.active_questions_json),
                    "focus_context": record.focus_context,
                    "available_minutes": record.available_minutes,
                    "preferred_depth": record.preferred_depth,
                    "exploration_level": record.exploration_level,
                }
            )
        snapshot = CurrentUserStateSnapshot(analysis_id=analysis.id, payload_json=payload)
        session.add(snapshot)
        session.flush()
        analysis.current_user_state_snapshot_id = snapshot.id
        return CurrentUserState.model_validate(payload)


def _state_expired(valid_until) -> bool:
    """判断当前状态是否过期；无有效期视为长期有效。"""

    if valid_until is None:
        return False
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=utc_now().tzinfo)
    return valid_until <= utc_now()


def _evaluation_delta_summary(analysis_id: str) -> dict | None:
    """读取 Compare 结果作为 Evaluate 的认知差异输入。

    Compare 未完成、失败或旧分析时返回 None，Evaluate 走保守逻辑；
    不生成占位 Delta，也不把召回失败当成用户无知。
    """

    with SessionLocal() as session:
        analysis = session.get(Analysis, analysis_id)
        if analysis is None or not analysis.cognitive_compare_run_id:
            return None
        run = session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
        if run is None or run.status != "completed" or not run.derived_summary_json:
            return None
        summary = dict(run.derived_summary_json)
        # 附上召回上下文与逐 Claim 证据，供 Evaluate 引用而不是自行发明。
        summary["retrieval_context"] = run.retrieval_context_json
        summary["relations"] = (run.compare_output_json or {}).get("relations", [])
        return summary


def _save_triage(analysis_id: str, triage: TriageContent) -> None:
    """持久化快速分诊结果并推进到正文分析阶段。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.triage_json = triage.model_dump(mode="json")
        job.stage = "analyze"


def _save_content_analysis(analysis_id: str, result: AnalyzeContent) -> None:
    """持久化内容本体分析并推进到 Claims 落库阶段。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.content_analysis_json = result.model_dump(mode="json")
        job.stage = "persist_claims"


def _persist_claims(analysis_id: str) -> None:
    """把当前分析的 Claims 分配稳定 ID 并写入行级记录。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        persist_claims(
            session,
            analysis_id=analysis.id,
            content_revision_id=analysis.content_revision_id,
            model=analysis.model,
            prompt_version=analysis.prompt_version,
        )
        job.stage = "retrieve_memory"


def _analysis_claim_dicts(session, analysis_id: str) -> list[dict]:
    """从 content_analysis_json 读取带稳定 claim_id 的 Claims 字典。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None or not analysis.content_analysis_json:
        return []
    payload = with_normalized_claims(dict(analysis.content_analysis_json))
    claims = payload.get("claims") or []
    return [
        item
        for item in claims
        if isinstance(item, dict) and item.get("claim_id") and item.get("claim")
    ]


def _retrieve_memory_candidates(analysis_id: str) -> None:
    """创建或复用 CompareRun，并保存本次 current / historical 候选。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        existing_run = None
        if analysis.cognitive_compare_run_id:
            existing_run = session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
        claims = _analysis_claim_dicts(session, analysis_id)
        if not claims:
            # 没有可比较的 Claims：创建完成的空 Run，Evaluate 走保守逻辑。
            if existing_run is None:
                existing_run = CognitiveCompareRun(
                    analysis_id=analysis_id,
                    current_claim_ids_json=[],
                    model=analysis.model,
                    prompt_version=analysis.prompt_version,
                    status="completed",
                    completed_at=utc_now(),
                )
                session.add(existing_run)
                session.flush()
                analysis.cognitive_compare_run_id = existing_run.id
            analysis.retrieval_context_status = "insufficient"
            job.stage = "evaluate"
            return

        result = retrieve_memory_candidates(session, claims)
        if existing_run is None:
            existing_run = CognitiveCompareRun(
                analysis_id=analysis_id,
                current_claim_ids_json=[item["claim_id"] for item in claims],
                current_memory_candidate_revision_ids_json=result.current_revision_ids,
                historical_memory_candidate_revision_ids_json=result.historical_revision_ids,
                retrieval_context_json=result.context.as_dict(),
                model=analysis.model,
                prompt_version=analysis.prompt_version,
            )
            session.add(existing_run)
            session.flush()
            analysis.cognitive_compare_run_id = existing_run.id
        else:
            existing_run.current_claim_ids_json = [item["claim_id"] for item in claims]
            existing_run.current_memory_candidate_revision_ids_json = result.current_revision_ids
            existing_run.historical_memory_candidate_revision_ids_json = (
                result.historical_revision_ids
            )
            existing_run.retrieval_context_json = result.context.as_dict()
            existing_run.model = analysis.model
            existing_run.prompt_version = analysis.prompt_version
            existing_run.status = "pending"
            existing_run.compare_output_json = None
            existing_run.derived_summary_json = None
            existing_run.last_error = None
            existing_run.completed_at = None
        analysis.retrieval_context_status = result.context.status
        job.stage = "compare"


def _run_compare_stage(provider: StructuredOutputProvider, analysis_id: str) -> None:
    """执行逐 Claim 认知比较并持久化 Delta；失败时保守降级到 Evaluate。

    召回错误或模型失败不生成占位 Delta，Analysis 仍继续 Evaluate；
    CompareRun 保留失败原因，用户可单独重试 Compare。
    """

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        run = session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
        if run is None:
            # 旧分析没有 CompareRun（legacy）：跳过 Compare，保守 Evaluate。
            job.stage = "evaluate"
            return
        if run.status == "completed":
            job.stage = "evaluate"
            return

        claims = _analysis_claim_dicts(session, analysis_id)
        current_ids = list(run.current_memory_candidate_revision_ids_json)
        historical_ids = list(run.historical_memory_candidate_revision_ids_json)
        if run.retrieval_context_json.get("retrieval_error"):
            run.status = "failed"
            run.last_error = "召回失败：" + str(run.retrieval_context_json.get("retrieval_error"))
            run.completed_at = utc_now()
            job.stage = "evaluate"
            return

        revisions = {}
        if current_ids or historical_ids:
            rows = session.scalars(
                select(CognitiveMemoryRevision).where(
                    CognitiveMemoryRevision.id.in_(current_ids + historical_ids)
                )
            ).all()
            revisions = {item.id: item for item in rows}

        def _candidate_dicts(revision_ids: list[str]) -> list[dict]:
            return [
                {
                    "revision_id": revision.id,
                    "memory_id": revision.cognitive_memory_id,
                    "statement": revision.statement,
                    "awareness_state": revision.awareness_state,
                    "stance": revision.stance,
                    "lifecycle": revision.lifecycle,
                    "version": revision.version,
                    "topics": list(revision.topics_json),
                    "entities": list(revision.entities_json),
                }
                for revision_id in revision_ids
                if (revision := revisions.get(revision_id)) is not None
            ]

        current_candidates = _candidate_dicts(current_ids)
        historical_candidates = _candidate_dicts(historical_ids)
        run.status = "running"
        run.model = analysis.model
        run.prompt_version = PROMPT_VERSION
        try:
            output = run_cognitive_compare(
                provider,
                claims=claims,
                current_candidates=current_candidates,
                historical_candidates=historical_candidates,
                retrieval_context=run.retrieval_context_json,
            )
            validate_compare_output(
                output,
                claim_ids=[item["claim_id"] for item in claims],
                current_candidate_ids=current_ids,
                historical_candidate_ids=historical_ids,
            )
        except Exception as exc:  # noqa: BLE001 - 模型或结构校验失败统一降级
            run.status = "failed"
            run.last_error = str(exc)
            run.completed_at = utc_now()
            job.stage = "evaluate"
            return

        awareness = {
            revision_id: revision.awareness_state
            for revision_id, revision in revisions.items()
        }
        run.compare_output_json = output.model_dump(mode="json")
        run.derived_summary_json = derive_delta_summary(
            output,
            claims=claims,
            current_candidate_ids=current_ids,
            historical_candidate_ids=historical_ids,
            current_revision_awareness=awareness,
            retrieval_context=run.retrieval_context_json,
        )
        run.status = "completed"
        run.completed_at = utc_now()
        run.last_error = None
        analysis.retrieval_context_status = run.retrieval_context_json.get("status")
        job.stage = "evaluate"


def _save_evaluation(
    analysis_id: str,
    result: EvaluateForUser,
    content_analysis: AnalyzeContent,
) -> None:
    """持久化最终建议并将分析任务标记为完成。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.personal_evaluation_json = result.model_dump(mode="json")
        analysis.status = "completed"
        analysis.completed_at = utc_now()
        job.stage = "completed"
        job.status = "completed"
        job.last_error = None
        # 记录选择性阅读章节计划的引用完整率，供真实文章评测使用；
        # 校验失败只降级引导流，不影响分析任务本身。
        try:
            if result.recommendation == "selective_read" and analysis.section_index_json:
                section_index = SectionIndex.model_validate(analysis.section_index_json)
                reason = validate_guided_flow(
                    section_index,
                    content_analysis.content_map,
                    result.reading_plan,
                )
                if reason is None:
                    LOGGER.info(
                        "引导流校验通过（%s）：%s 个主章节",
                        analysis_id,
                        len(section_index.sections),
                    )
                else:
                    LOGGER.warning("引导流校验未通过（%s）：%s", analysis_id, reason)
        except (TypeError, ValueError):
            LOGGER.warning("引导流校验数据异常（%s），按降级处理", analysis_id)


def _complete_analysis(analysis_id: str) -> None:
    """完成被快速分诊忽略的自动采集内容。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.status = "completed"
        analysis.completed_at = utc_now()
        job.stage = "completed"
        job.status = "completed"
        job.last_error = None


def _save_translation_batch(translation_id: str, result) -> None:
    """保存一批译文和进度，使长文失败后可以从断点继续。"""

    translated = {item.id: item.translated_markdown for item in result.translations}
    with SessionLocal.begin() as session:
        translation = session.get(ContentTranslation, translation_id)
        if translation is None or translation.status != "running":
            raise RuntimeError(f"翻译任务状态异常：{translation_id}")
        blocks = [dict(block) for block in translation.blocks_json]
        for block in blocks:
            if block["id"] in translated:
                block["translated_markdown"] = translated[block["id"]]
        translation.blocks_json = blocks
        translation.completed_blocks = sum(
            bool(block.get("translated_markdown"))
            for block in blocks
            if block["translatable"]
        )


def _complete_translation(translation_id: str) -> None:
    """确认所有可翻译块已完成，再结束翻译任务。"""

    with SessionLocal.begin() as session:
        translation = session.get(ContentTranslation, translation_id)
        if translation is None or translation.status != "running":
            raise RuntimeError(f"翻译任务状态异常：{translation_id}")
        if translation.completed_blocks != translation.total_blocks:
            raise RuntimeError(
                f"翻译块未全部完成：{translation.completed_blocks}/{translation.total_blocks}"
            )
        translation.status = "completed"
        translation.completed_at = utc_now()
        translation.last_error = None


def _fail_analysis(analysis_id: str, error: Exception) -> None:
    """记录可诊断的失败状态，不删除已经入库的原始内容。"""

    with SessionLocal.begin() as session:
        analysis = session.get(Analysis, analysis_id)
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        if analysis is not None:
            analysis.status = "failed"
            analysis.completed_at = utc_now()
        if job is not None:
            job.status = "failed"
            job.last_error = str(error)


def _fail_translation(translation_id: str, error: Exception) -> None:
    """记录翻译失败原因，但保留已经成功的批次。"""

    with SessionLocal.begin() as session:
        translation = session.get(ContentTranslation, translation_id)
        if translation is not None:
            translation.status = "failed"
            translation.completed_at = utc_now()
            translation.last_error = str(error)


def _load_running_task(session, analysis_id: str) -> tuple[Analysis, AnalysisJob]:
    """读取刚被当前 Worker 领取的分析及任务记录。"""

    analysis = session.get(Analysis, analysis_id)
    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
    if analysis is None or job is None or job.status != "running":
        raise RuntimeError(f"分析任务状态异常：{analysis_id}")
    return analysis, job


def run() -> None:
    """启动 Worker 循环，配置有效模型后持续消费待处理任务。"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    create_schema()
    LOGGER.info("SignalLens Worker 已启动，待处理任务：%s", pending_job_count())
    provider = build_provider_from_settings()
    if provider is None:
        LOGGER.warning("未配置 LLM，Worker 仅保持运行，不消费任务")
        while True:
            time.sleep(5)
    while True:
        analysis_processed = process_next_job(provider)
        translation_processed = process_next_translation(provider)
        if not analysis_processed and not translation_processed:
            time.sleep(2)
