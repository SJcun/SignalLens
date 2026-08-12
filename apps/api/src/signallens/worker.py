"""持久化分析任务 Worker。"""

import logging
import time

from sqlalchemy import func, select, update

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
from .models import Analysis, AnalysisJob, Content, utc_now
from .settings import get_settings

LOGGER = logging.getLogger("signallens.worker")


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

    analysis_id, content = claimed
    user_profile = profile or UserProfile()
    try:
        triage = run_triage(provider, content, user_profile)
        _save_triage(analysis_id, triage)
        if triage.decision == "ignore":
            _complete_analysis(analysis_id)
            return True

        content_analysis = run_content_analysis(provider, content, triage)
        _save_content_analysis(analysis_id, content_analysis)
        evaluation = run_personal_evaluation(provider, content_analysis, user_profile)
        _save_evaluation(analysis_id, evaluation)
        return True
    except Exception as exc:
        # 单条模型失败不能结束 Worker；失败状态保留原因，便于后续人工重试。
        _fail_analysis(analysis_id, exc)
        LOGGER.exception("分析任务失败：%s", analysis_id)
        return True


def _claim_next_job(model: str) -> tuple[str, AnalysisInput] | None:
    """使用条件更新领取最早任务，防止多个 Worker 重复消费。"""

    with SessionLocal.begin() as session:
        candidate_id = session.scalar(
            select(AnalysisJob.id)
            .where(AnalysisJob.status == "pending")
            .order_by(AnalysisJob.created_at)
            .limit(1)
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
        return analysis.id, AnalysisInput(
            title=content.title,
            source_url=content.source_url,
            source_type=content.source_type,
            capture_mode=content.capture_mode,
            capture_quality=content.capture_quality,
            markdown=content.markdown,
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
    )
    while True:
        if not process_next_job(provider):
            time.sleep(2)
