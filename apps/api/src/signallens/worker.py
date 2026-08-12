"""分析 Worker 入口；当前只验证环境，Prompt 实现将在阶段 0 接入。"""

import logging
import time

from sqlalchemy import func, select

from .database import SessionLocal, create_schema
from .models import AnalysisJob
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


def run() -> None:
    """启动 Worker 循环；未配置模型时保持任务不变，防止产生伪分析结果。"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    create_schema()
    settings = get_settings()
    LOGGER.info("SignalLens Worker 已启动，待处理任务：%s", pending_job_count())
    if not settings.llm_api_key or not settings.llm_model:
        LOGGER.warning("未配置 LLM，Worker 仅保持运行，不消费任务")
    while True:
        # 阶段 0 完成 Prompt 与评测后，再在此领取并执行任务。
        time.sleep(5)

