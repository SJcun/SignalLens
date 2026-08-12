"""SignalLens 第一阶段持久化模型。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """生成带时区的 UTC 时间。"""

    return datetime.now(UTC)


def new_id() -> str:
    """生成适合 API 暴露的 UUID 字符串。"""

    return str(uuid4())


class Content(Base):
    """用户提交的统一内容快照。"""

    __tablename__ = "contents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    capture_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    capture_mode: Mapped[str] = mapped_column(String(16), default="manual")
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown: Mapped[str] = mapped_column(Text)
    capture_quality: Mapped[str] = mapped_column(String(16))
    capture_payload_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="content")


class Analysis(Base):
    """一次可追踪、可重新执行的内容分析。"""

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    triage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_analysis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    personal_evaluation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="unimplemented")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    content: Mapped[Content] = relationship(back_populates="analyses")
    job: Mapped["AnalysisJob"] = relationship(back_populates="analysis", uselist=False)


class AnalysisJob(Base):
    """由独立 Worker 消费的持久化分析任务。"""

    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), unique=True, index=True)
    stage: Mapped[str] = mapped_column(String(32), default="triage")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    analysis: Mapped[Analysis] = relationship(back_populates="job")
