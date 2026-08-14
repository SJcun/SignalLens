"""持久化分析任务 Worker。"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy import case, func, select, update

from .analysis.pipeline import (
    AnalysisInput,
    StructuredOutputProvider,
    run_content_analysis,
    run_personal_evaluation,
    run_triage,
)
from .analysis.prompts import PROMPT_VERSION
from .analysis.provider import OpenAICompatibleProvider
from .analysis.schemas import AnalyzeContent, EvaluateForUser, TriageContent, UserProfile
from .database import SessionLocal, create_schema
from .models import (
    Analysis,
    AnalysisJob,
    AnalysisSchedule,
    Content,
    ContentTranslation,
    UserProfileRecord,
    utc_now,
)
from .scheduling import is_within_windows
from .settings import get_settings
from .translation import (
    TRANSLATION_PROMPT_VERSION,
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
                stage = "evaluate"
            elif stage == "evaluate" and content_analysis is not None:
                evaluation = run_personal_evaluation(
                    provider,
                    content_analysis,
                    user_profile,
                )
                _save_evaluation(analysis_id, evaluation)
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
            ),
            triage=(
                TriageContent.model_validate(analysis.triage_json)
                if analysis.triage_json
                else None
            ),
            content_analysis=(
                AnalyzeContent.model_validate(analysis.content_analysis_json)
                if analysis.content_analysis_json
                else None
            ),
        )


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


def _save_triage(analysis_id: str, triage: TriageContent) -> None:
    """持久化快速分诊结果并推进到正文分析阶段。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.triage_json = triage.model_dump(mode="json")
        job.stage = "analyze"


def _save_content_analysis(analysis_id: str, result: AnalyzeContent) -> None:
    """持久化内容本体分析并推进到个性化评估阶段。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.content_analysis_json = result.model_dump(mode="json")
        job.stage = "evaluate"


def _save_evaluation(analysis_id: str, result: EvaluateForUser) -> None:
    """持久化最终建议并将分析任务标记为完成。"""

    with SessionLocal.begin() as session:
        analysis, job = _load_running_task(session, analysis_id)
        analysis.personal_evaluation_json = result.model_dump(mode="json")
        analysis.status = "completed"
        analysis.completed_at = utc_now()
        job.stage = "completed"
        job.status = "completed"
        job.last_error = None


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
    settings = get_settings()
    LOGGER.info("SignalLens Worker 已启动，待处理任务：%s", pending_job_count())
    if not settings.llm_api_key or not settings.llm_model:
        LOGGER.warning("未配置 LLM，Worker 仅保持运行，不消费任务")
        while True:
            time.sleep(5)

    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        response_format_mode=settings.llm_response_format,
        max_tokens=settings.llm_max_tokens,
    )
    while True:
        analysis_processed = process_next_job(provider)
        translation_processed = process_next_translation(provider)
        if not analysis_processed and not translation_processed:
            time.sleep(2)
