"""API 输入、输出和未来 AI 结构化结果的数据契约。"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .analysis.schemas import AnalyzeContent, EvaluateForUser, TriageContent


def attach_utc(value: datetime | None) -> datetime | None:
    """SQLite 返回无时区时间时，将其按数据库约定解释为 UTC。"""

    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class SourcePayload(BaseModel):
    """内容的原始来源信息。"""

    type: Literal["web", "pdf", "youtube", "bilibili", "podcast", "audio", "video"]
    url: HttpUrl
    canonical_url: HttpUrl | None = None
    title: str = Field(min_length=1, max_length=1000)
    author: str | None = Field(default=None, max_length=500)


class DocumentPayload(BaseModel):
    """供分析管线消费的标准化文本。"""

    format: Literal["markdown", "transcript"]
    text: str = Field(min_length=1)
    units: list[dict] = Field(default_factory=list)


class QualityPayload(BaseModel):
    """采集器给出的内容质量判断。"""

    level: Literal["good", "warning", "poor", "failed"]
    warnings: list[str] = Field(default_factory=list)


class CaptureMetadata(BaseModel):
    """本次采集的方式、生产者与质量。"""

    mode: Literal["manual", "automatic"] = "manual"
    producer: str
    producer_version: str
    quality: QualityPayload
    extraction_engine: str


class CaptureRequest(BaseModel):
    """浏览器插件和未来 Adapter 共用的采集协议。"""

    schema_version: Literal["signallens.capture.v1"]
    capture_id: str = Field(min_length=8, max_length=64)
    source: SourcePayload
    document: DocumentPayload
    capture: CaptureMetadata


class CaptureAccepted(BaseModel):
    """内容可靠入库后的异步任务标识。"""

    content_id: str
    analysis_id: str
    status: Literal["pending", "running", "completed", "failed"]
    detail_url: str


class AnalysisResponse(BaseModel):
    """Web 和插件轮询使用的分析状态。"""

    id: str
    content_id: str
    status: Literal["pending", "running", "completed", "failed"]
    triage: TriageContent | None
    content_analysis: AnalyzeContent | None
    personal_evaluation: EvaluateForUser | None
    created_at: datetime
    completed_at: datetime | None

    _normalize_created_at = field_validator("created_at", mode="before")(attach_utc)
    _normalize_completed_at = field_validator("completed_at", mode="before")(attach_utc)


class ContentSummaryResponse(BaseModel):
    """Inbox 使用的内容摘要与最新分析状态。"""

    id: str
    title: str
    author: str | None
    source_url: str
    source_type: str
    capture_quality: str
    created_at: datetime
    analysis_id: str
    analysis_status: Literal["pending", "running", "completed", "failed"]
    one_sentence_summary: str | None
    recommendation: str | None
    discovery_type: str | None

    _normalize_created_at = field_validator("created_at", mode="before")(attach_utc)


class KnownTopicPayload(BaseModel):
    """用户明确声明的知识领域及熟悉程度。"""

    topic: str = Field(min_length=1, max_length=100)
    level: Literal["basic", "intermediate", "advanced"]


class ProfileUpdate(BaseModel):
    """初始问卷和后续手动调整共用的画像输入。"""

    focus_topics: list[str] = Field(min_length=1, max_length=5)
    known_topics: list[KnownTopicPayload] = Field(default_factory=list, max_length=10)
    reading_goals: list[
        Literal["solve_problems", "systematic_learning", "follow_updates", "explore"]
    ] = Field(min_length=1, max_length=4)
    preferred_depth: Literal["quick", "balanced", "deep"]
    time_budget_minutes: int = Field(ge=5, le=120)
    exploration_level: Literal["low", "medium", "high"]
    evaluation_mode: bool


class ProfileResponse(BaseModel):
    """当前单用户画像和问卷状态。"""

    focus_topics: list[str]
    known_topics: list[KnownTopicPayload]
    reading_goals: list[str]
    preferred_depth: Literal["quick", "balanced", "deep"]
    time_budget_minutes: int
    exploration_level: Literal["low", "medium", "high"]
    evaluation_mode: bool
    questionnaire_completed: bool
    updated_at: datetime

    _normalize_updated_at = field_validator("updated_at", mode="before")(attach_utc)


class FeedbackUpsert(BaseModel):
    """阅读后提交的最小人工评价。"""

    recommendation_accuracy: Literal["too_high", "accurate", "too_low"]
    time_worthwhile: Literal["no", "partly", "yes"]
    new_knowledge: Literal["none", "some", "much"]
    summary_quality: Literal["accurate", "omission", "misleading", "not_sure"]
    key_takeaway: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(FeedbackUpsert):
    """文章详情页回显的人工评价。"""

    id: str
    analysis_id: str
    ai_recommendation: str | None
    model: str | None
    prompt_version: str
    updated_at: datetime

    _normalize_updated_at = field_validator("updated_at", mode="before")(attach_utc)


class ContentDetailResponse(ContentSummaryResponse):
    """内容详情页需要的原文快照与完整分析结果。"""

    markdown: str
    triage: TriageContent | None
    content_analysis: AnalyzeContent | None
    personal_evaluation: EvaluateForUser | None
    feedback: FeedbackResponse | None


class CalibrationStatsResponse(BaseModel):
    """评测模式所需的基础校准指标。"""

    evaluation_mode: bool
    questionnaire_completed: bool
    completed_analyses: int
    feedback_count: int
    accurate_count: int
    too_high_count: int
    too_low_count: int
    accuracy_rate: float | None
    summary_issue_count: int
    high_value_miss_count: int


class HealthResponse(BaseModel):
    """部署探针使用的健康状态。"""

    status: Literal["ok"]
    service: Literal["signallens-api"]


class LoginRequest(BaseModel):
    """管理员账号密码登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """供 Web 和插件保存的 Bearer 会话。"""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    username: str
    must_change_password: bool
    expires_at: datetime

    _normalize_expires_at = field_validator("expires_at", mode="before")(attach_utc)


class CurrentUserResponse(BaseModel):
    """当前登录账户的公开状态。"""

    username: str
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    """登录后修改管理员密码。"""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class MessageResponse(BaseModel):
    """无需额外业务字段的操作结果。"""

    message: str
