"""API 输入、输出和未来 AI 结构化结果的数据契约。"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from .analysis.schemas import AnalyzeContent, EvaluateForUser, Recommendation, TriageContent
from .analysis.sections import SectionIndex


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


class AnalysisQueueState(BaseModel):
    """Web 展示任务调度原因所需的最小队列状态。"""

    stage: Literal["triage", "analyze", "evaluate", "completed"]
    execution_mode: Literal["scheduled", "immediate"]
    waiting_for_schedule: bool
    next_eligible_at: datetime | None

    _normalize_next_eligible_at = field_validator("next_eligible_at", mode="before")(
        attach_utc
    )


class CaptureAccepted(BaseModel):
    """内容可靠入库后的异步任务标识。"""

    content_id: str
    analysis_id: str
    status: Literal["pending", "running", "completed", "failed"]
    detail_url: str
    queue: AnalysisQueueState


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
    queue: AnalysisQueueState

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
    recommendation: Recommendation | None
    ai_recommendation: Recommendation | None
    user_recommendation: Recommendation | None
    discovery_type: str | None
    queue: AnalysisQueueState

    _normalize_created_at = field_validator("created_at", mode="before")(attach_utc)


class AnalysisWindow(BaseModel):
    """每天重复的一段北京时间整理窗口。"""

    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AnalysisScheduleUpdate(BaseModel):
    """总开关和每日时段的完整更新请求。"""

    enabled: bool
    windows: list[AnalysisWindow] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_schedule_windows(self):
        """统一校验跨午夜和多窗口重叠。"""

        from .scheduling import validate_windows

        validate_windows([item.model_dump() for item in self.windows])
        return self


class AnalysisScheduleResponse(AnalysisScheduleUpdate):
    """整理设置、当前门禁状态和等待任务数量。"""

    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    currently_allowed: bool
    next_window_start: datetime | None
    scheduled_job_count: int
    updated_at: datetime

    _normalize_next_window_start = field_validator("next_window_start", mode="before")(
        attach_utc
    )
    _normalize_updated_at = field_validator("updated_at", mode="before")(attach_utc)


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

    preferred_recommendation: Recommendation
    time_worthwhile: Literal["no", "partly", "yes"]
    new_knowledge: Literal["none", "some", "much"]
    summary_quality: Literal["accurate", "omission", "misleading", "not_sure"]
    key_takeaway: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    """文章详情页回显的人工评价。"""

    id: str
    analysis_id: str
    preferred_recommendation: Recommendation | None
    recommendation_accuracy: Literal["too_high", "accurate", "too_low"]
    time_worthwhile: Literal["no", "partly", "yes"]
    new_knowledge: Literal["none", "some", "much"]
    summary_quality: Literal["accurate", "omission", "misleading", "not_sure"]
    key_takeaway: str | None
    ai_recommendation: str | None
    model: str | None
    prompt_version: str
    updated_at: datetime

    _normalize_updated_at = field_validator("updated_at", mode="before")(attach_utc)


class TranslationBlockResponse(BaseModel):
    """详情页中保持同一位置的一组原文与译文。"""

    id: str
    kind: Literal["heading", "paragraph", "list", "quote", "table", "code", "image", "separator"]
    source_markdown: str
    translated_markdown: str | None
    shared: bool
    # 块在原文中的行号范围（零起点、左闭右开），与 section_index 口径一致；
    # 旧数据或正文与译文不一致时为 None，引导流退回逐节原文。
    start_line: int | None = None
    end_line: int | None = None


class TranslationResponse(BaseModel):
    """正文翻译任务状态、进度和已完成内容块。"""

    id: str
    status: Literal["pending", "running", "completed", "failed"]
    source_language: str
    target_language: Literal["zh-CN"]
    completed_blocks: int
    total_blocks: int
    blocks: list[TranslationBlockResponse]
    model: str | None
    prompt_version: str
    last_error: str | None
    created_at: datetime
    completed_at: datetime | None

    _normalize_created_at = field_validator("created_at", mode="before")(attach_utc)
    _normalize_completed_at = field_validator("completed_at", mode="before")(attach_utc)


class ContentDetailResponse(ContentSummaryResponse):
    """内容详情页需要的原文快照与完整分析结果。"""

    markdown: str
    source_language: str
    translation: TranslationResponse | None
    triage: TriageContent | None
    content_analysis: AnalyzeContent | None
    personal_evaluation: EvaluateForUser | None
    feedback: FeedbackResponse | None
    # 系统主章节清单；正文哈希与分析快照不一致时为 None，避免引用错位。
    section_index: SectionIndex | None
    # 是否启用顺序式引导阅读流；False 时正文整体退回完整原文模式。
    guided_flow_available: bool


class CalibrationMatrixCell(BaseModel):
    """AI 原建议与用户最终等级的一个有效对照单元。"""

    ai_recommendation: Recommendation
    user_recommendation: Recommendation
    count: int


class CalibrationSuggestionDecision(BaseModel):
    """用户对候选阅读规则的明确处理决定。"""

    decision: Literal["accepted", "rejected"]


class CalibrationSuggestionResponse(BaseModel):
    """达到样本门槛后由统计证据生成的候选规则。"""

    id: str
    title: str
    evidence: str
    proposed_rule: str
    status: Literal["pending", "accepted", "rejected"]


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
    feedback_needed: int
    adjacent_error_count: int
    major_error_count: int
    confusion_matrix: list[CalibrationMatrixCell]
    suggestions: list[CalibrationSuggestionResponse]


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


class PluginKeyStatusResponse(BaseModel):
    """Web 账户页可见的插件 Key 状态，不返回密钥明文。"""

    configured: bool
    key_prefix: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None

    _normalize_created_at = field_validator("created_at", mode="before")(attach_utc)
    _normalize_last_used_at = field_validator("last_used_at", mode="before")(attach_utc)


class GeneratedPluginKeyResponse(BaseModel):
    """生成时唯一一次返回完整插件 Key。"""

    api_key: str
    key_prefix: str
    created_at: datetime

    _normalize_created_at = field_validator("created_at", mode="before")(attach_utc)
