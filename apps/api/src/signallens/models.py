"""SignalLens 第一阶段持久化模型。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
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


class UserProfileRecord(Base):
    """单用户阶段的显式阅读画像和评测模式设置。"""

    __tablename__ = "user_profile"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    focus_topics_json: Mapped[list] = mapped_column(JSON, default=list)
    known_topics_json: Mapped[list] = mapped_column(JSON, default=list)
    reading_goals_json: Mapped[list] = mapped_column(JSON, default=list)
    preferred_depth: Mapped[str] = mapped_column(String(32), default="balanced")
    time_budget_minutes: Mapped[int] = mapped_column(Integer, default=20)
    exploration_level: Mapped[str] = mapped_column(String(16), default="medium")
    evaluation_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    calibration_decisions_json: Mapped[dict | None] = mapped_column(
        JSON, default=dict, nullable=True
    )
    questionnaire_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ArticleFeedback(Base):
    """用户对一次 AI 分析的人工评价及提交时的结果快照。"""

    __tablename__ = "article_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id"), index=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id"), unique=True, index=True
    )
    preferred_recommendation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommendation_accuracy: Mapped[str] = mapped_column(String(16))
    time_worthwhile: Mapped[str] = mapped_column(String(16))
    new_knowledge: Mapped[str] = mapped_column(String(16))
    summary_quality: Mapped[str] = mapped_column(String(16))
    key_takeaway: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_recommendation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32))
    analysis_snapshot_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AdminUser(Base):
    """单用户阶段的管理员账户。"""

    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuthSession(Base):
    """Web 管理员登录后创建的可撤销会话。"""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PluginApiKey(Base):
    """允许浏览器插件提交采集内容的单一最小权限密钥。"""

    __tablename__ = "plugin_api_key"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
