"""三阶段 AI 阅读分诊的结构化输出契约。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SignalLevel = Literal["low", "medium", "high"]
RelevanceLevel = Literal["low", "medium", "high", "very_high"]
DiscoveryType = Literal["profile_match", "adjacent", "outside_profile_high_value"]
Recommendation = Literal["ignore", "summary_enough", "selective_read", "deep_read"]
ShortText = Annotated[str, Field(min_length=1, max_length=240)]
CompactText = Annotated[str, Field(min_length=1, max_length=400)]
SummaryText = Annotated[str, Field(min_length=1, max_length=1600)]


class StrictOutputModel(BaseModel):
    """禁止额外字段，使生成的 JSON Schema 可用于严格结构化输出。"""

    model_config = ConfigDict(extra="forbid")


class TriageContent(StrictOutputModel):
    """快速判断内容是否值得继续投入分析资源。"""

    relevance: RelevanceLevel
    intrinsic_signal: SignalLevel
    novelty_signal: Literal["low", "medium", "high", "unknown"]
    exploration_value: SignalLevel
    discovery_type: DiscoveryType
    decision: Literal["ignore", "continue"]
    reason: CompactText
    why_outside_profile: CompactText | None

    @model_validator(mode="after")
    def validate_ignore_decision(self) -> "TriageContent":
        """禁止仅因相关性低而忽略仍有内容或探索价值的文章。"""

        if self.decision == "ignore" and (
            self.intrinsic_signal != "low" or self.exploration_value != "low"
        ):
            raise ValueError("只有内容信号和探索价值都低时才允许忽略")
        if self.discovery_type == "outside_profile_high_value" and not self.why_outside_profile:
            raise ValueError("画像外高价值内容必须说明探索价值")
        return self


class ContentProfile(StrictOutputModel):
    """文章自身的主题、类型和理解门槛。"""

    topics: list[ShortText] = Field(max_length=8)
    content_type: ShortText
    difficulty: Literal["introductory", "intermediate", "advanced"]


class ContentSection(StrictOutputModel):
    """文章中可独立定位和阅读的章节。

    section_ref 由系统章节清单提供，模型只复制引用、不能创造；
    历史结果没有引用时允许为空，Web 不能使用标题文本猜测位置。
    """

    section_ref: str | None = None
    title: ShortText
    summary: CompactText


class ContentClaim(StrictOutputModel):
    """文章提出的可独立比较的主张及原文证据状态。

    claim_id 由系统在持久化阶段分配（如 claim-001），模型不输出；
    claim_role 区分核心观点、重要支撑和边缘细节，一个 Claim 只有一个角色；
    change_signal 描述原文是否出现时间、版本、替代或废弃信号，
    没有原文证据时必须为 none，用于触发历史 Memory 召回；
    section_ref 必须来自系统章节清单，模型只能复制引用、不能创造。
    """

    # 系统在持久化 Claims 时分配的稳定 ID；模型输出中始终为空。
    claim_id: str | None = None
    claim: CompactText
    claim_type: Literal["fact", "interpretation", "opinion", "prediction", "recommendation", "definition"]
    claim_role: Literal["core", "supporting", "detail"]
    change_signal: Literal["none", "temporal", "version", "replacement", "deprecation"] = "none"
    section_ref: str | None = None
    evidence: list[CompactText] = Field(max_length=4)
    verification: Literal["supported_in_content", "unverified", "opinion"]
    topics: list[ShortText] = Field(default_factory=list, max_length=5)
    entities: list[ShortText] = Field(default_factory=list, max_length=5)


class AnalyzeContent(StrictOutputModel):
    """不读取完整用户画像的内容本体分析结果。"""

    one_sentence_summary: ShortText
    summary: SummaryText
    content_profile: ContentProfile
    content_map: list[ContentSection] = Field(max_length=10)
    key_points: list[CompactText] = Field(max_length=10)
    claims: list[ContentClaim] = Field(max_length=8)
    thesis: SummaryText | None
    supporting_evidence: list[CompactText] = Field(max_length=8)
    counterarguments: list[CompactText] = Field(max_length=6)
    author_stance: CompactText | None
    limitations: list[CompactText] = Field(max_length=6)
    unresolved_questions: list[CompactText] = Field(max_length=6)
    unverified_claims: list[CompactText] = Field(max_length=6)


class ReadingPlanItem(StrictOutputModel):
    """针对某个章节给出的具体阅读动作。

    section_ref 与 content_map 使用同一套来源引用；旧结果没有引用时
    允许为空，此时只能展示为历史列表，不能参与引导阅读流。
    """

    section_ref: str | None = None
    section: ShortText
    action: Literal["skip", "skim", "read", "deep_read"]
    reason: CompactText


class EvaluateForUser(StrictOutputModel):
    """结合用户简要画像生成最终阅读建议。"""

    relevance: RelevanceLevel
    knowledge_overlap: SignalLevel
    known_or_redundant: bool
    novel_information: list[CompactText] = Field(max_length=8)
    exploration_value: SignalLevel
    perspective_diversity: SignalLevel
    discovery_type: DiscoveryType
    recommendation: Recommendation
    recommendation_reason: SummaryText
    why_outside_profile: CompactText | None
    # selective_read 时上限与第一版主章节上限一致，保证计划能完整覆盖全部章节。
    reading_plan: list[ReadingPlanItem] = Field(max_length=10)

    @model_validator(mode="after")
    def validate_exploration_recommendation(self) -> "EvaluateForUser":
        """保护低相关但高探索价值的内容，不允许直接建议忽略。"""

        if (
            self.exploration_value == "high"
            and self.recommendation == "ignore"
        ):
            raise ValueError("高探索价值内容不能建议忽略")
        if self.discovery_type == "outside_profile_high_value" and not self.why_outside_profile:
            raise ValueError("画像外高价值内容必须解释推荐原因")
        return self


class UserProfile(BaseModel):
    """V0.1 分析使用的最小用户画像，暂不包含行为推断。"""

    focus_topics: list[str] = Field(default_factory=list)
    known_topics: list[str] = Field(default_factory=list)
    reading_goals: list[str] = Field(default_factory=list)
    preferred_depth: str = "balanced"
    time_budget_minutes: int = 20
    exploration_level: str = "medium"


class CurrentUserState(BaseModel):
    """Evaluate 输入使用的当前阅读上下文；状态为空时使用保守默认值。

    只包含用户显式编辑的短时上下文，不承担长期认知存储；
    valid_until 过期或未设置时按空状态处理。
    """

    active_goals: list[str] = Field(default_factory=list)
    active_questions: list[str] = Field(default_factory=list)
    focus_context: str | None = None
    available_minutes: int | None = None
    preferred_depth: str | None = None
    exploration_level: str | None = None
