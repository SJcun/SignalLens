"""SignalLens 第一阶段持久化模型。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class ContentRevision(Base):
    """正文的一次不可变快照版本，正文变化时创建新 Revision。

    旧 Claim 和章节引用只对生成它的 Revision 有效；正文被重新采集后，
    新分析必须关联新 Revision，不能与旧 Claim 混用。
    """

    __tablename__ = "content_revisions"
    __table_args__ = (
        UniqueConstraint("content_id", "version", name="uq_content_revision_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    # 该版本正文的 SHA-256；同一内容的同一次正文共享同一 Revision。
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Analysis(Base):
    """一次可追踪、可重新执行的内容分析。"""

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id"), index=True)
    # 分析基于的正文 Revision；旧分析无法精确还原时为空，标记为 legacy。
    content_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_revisions.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    triage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_analysis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    personal_evaluation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 分析开始时正文快照的哈希，章节引用只对同一快照有效。
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 系统在模型调用前生成的主章节清单，属于系统元数据而非 AI 结论。
    section_index_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Evaluate 使用的 Current User State 不可变快照；旧分析为空。
    current_user_state_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 本次分析使用的 Cognitive Compare Run；旧分析或 Compare 失败时为空。
    cognitive_compare_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 代码计算的召回上下文状态，LLM 不能输出或修改；旧分析为空。
    retrieval_context_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="unimplemented")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    content: Mapped[Content] = relationship(back_populates="analyses")
    job: Mapped["AnalysisJob"] = relationship(back_populates="analysis", uselist=False)


class ContentClaim(Base):
    """一次内容分析中提取的行级主张，正文覆盖后仍保留当时的证据。

    系统在持久化时分配分析内稳定的 claim_id（如 claim-001），
    模型输出本身不携带数据库身份；旧分析没有行级记录时，
    Web 回退读取 content_analysis_json 中嵌套的 claims。
    """

    __tablename__ = "content_claims"
    __table_args__ = (
        UniqueConstraint("analysis_id", "claim_id", name="uq_content_claim_analysis_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    content_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_revisions.id"), nullable=True, index=True
    )
    # 分析内稳定 ID，如 claim-001；Compare 与纠错通过它引用当前 Claim。
    claim_id: Mapped[str] = mapped_column(String(32))
    # 该 Claim 在分析输出中的顺序，用于保持展示与输入顺序一致。
    claim_order: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(16))
    claim_role: Mapped[str] = mapped_column(String(16))
    # 原文是否出现时间、版本、替代或废弃信号；没有证据必须为 none。
    change_signal: Mapped[str] = mapped_column(String(16), default="none")
    # 来自系统章节清单的引用，校验失败时为空而不是伪造。
    section_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    verification: Mapped[str] = mapped_column(String(32))
    topics_json: Mapped[list] = mapped_column(JSON, default=list)
    entities_json: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="unimplemented")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalysisJob(Base):
    """由独立 Worker 消费的持久化分析任务。"""

    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), unique=True, index=True)
    stage: Mapped[str] = mapped_column(String(32), default="triage")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 非空表示用户明确要求绕过低价时段；时间用于立即任务之间保持先来先服务。
    immediate_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    analysis: Mapped[Analysis] = relationship(back_populates="job")


class AnalysisSchedule(Base):
    """单用户全局 AI 整理时段设置。"""

    __tablename__ = "analysis_schedule"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    # 关闭后恢复提交即分析，但保留窗口配置以便下次一键开启。
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    windows_json: Mapped[list] = mapped_column(
        JSON,
        default=lambda: [{"start": "00:00", "end": "08:00"}],
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ContentTranslation(Base):
    """正文快照对应的一份可断点续跑的结构保持译文。"""

    __tablename__ = "content_translations"
    __table_args__ = (
        UniqueConstraint("content_id", "target_language", name="uq_translation_content_target"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id"), index=True)
    source_language: Mapped[str] = mapped_column(String(32))
    target_language: Mapped[str] = mapped_column(String(32), default="zh-CN")
    source_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    blocks_json: Mapped[list] = mapped_column(JSON, default=list)
    completed_blocks: Mapped[int] = mapped_column(Integer, default=0)
    total_blocks: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="unimplemented")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class CognitiveMemory(Base):
    """一条用户认知的逻辑身份；内容只存在于 append-only Revision 中。

    指针 current_revision_id 原子指向当前有效版本，历史 Revision 永不覆盖。
    """

    __tablename__ = "cognitive_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("cognitive_memory_revisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CognitiveMemoryRevision(Base):
    """一条认知的不可变版本，创建、修正、标记过时都追加新版本。"""

    __tablename__ = "cognitive_memory_revisions"
    __table_args__ = (
        UniqueConstraint(
            "cognitive_memory_id", "version", name="uq_memory_revision_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cognitive_memory_id: Mapped[str] = mapped_column(
        ForeignKey("cognitive_memories.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    # 用户是否已经知道；没有已确认记录不创建 unknown Revision。
    awareness_state: Mapped[str] = mapped_column(String(16))
    # 用户立场与知晓状态分开保存："知道但反对"是合法状态。
    stance: Mapped[str] = mapped_column(String(16))
    # 该认知当前是否仍有效；过时认知仍可被 change signal 召回用于 updates。
    lifecycle: Mapped[str] = mapped_column(String(16), default="active")
    # 系统对"Revision 是否准确记录用户认知"的把握，不代表主张客观为真。
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    topics_json: Mapped[list] = mapped_column(JSON, default=list)
    entities_json: Mapped[list] = mapped_column(JSON, default=list)
    # manual / claim_feedback / accepted_proposal
    source_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CognitiveMemoryEvidence(Base):
    """Revision 与来源 Claim 的显式关联；手工录入可以没有 Claim 来源。"""

    __tablename__ = "cognitive_memory_evidence"
    __table_args__ = (
        UniqueConstraint(
            "cognitive_memory_revision_id",
            "content_claim_id",
            "evidence_role",
            name="uq_memory_evidence_claim_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cognitive_memory_revision_id: Mapped[str] = mapped_column(
        ForeignKey("cognitive_memory_revisions.id"), index=True
    )
    content_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_claims.id"), nullable=True, index=True
    )
    # supports / contradicts / updates / origin
    evidence_role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MemoryConfirmationEvent(Base):
    """append-only 的用户确认记录，不代表 Memory 内容变化。"""

    __tablename__ = "memory_confirmation_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cognitive_memory_id: Mapped[str] = mapped_column(
        ForeignKey("cognitive_memories.id"), index=True
    )
    # 确认发生时看到的 current Revision；没有对应版本时为空。
    observed_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # manual / claim_feedback / accepted_proposal
    source_type: Mapped[str] = mapped_column(String(32))
    content_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_claims.id"), nullable=True
    )
    source_feedback_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # already_known / learned_now / awareness_confirmed / stance_confirmed / source_confirmed
    confirmation_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MemoryChangeProposal(Base):
    """未确认的 Memory 修改建议；只有 accepted 才能改变正式状态。"""

    __tablename__ = "memory_change_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # CREATE / REVISE / MARK_OBSOLETE / REACTIVATE / RESOLVE_MATCH
    action: Mapped[str] = mapped_column(String(16))
    target_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("cognitive_memories.id"), nullable=True, index=True
    )
    # 接受时校验当前指针仍是这个版本，防止覆盖较新的用户修改。
    expected_current_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # RESOLVE_MATCH 保存用户决策时看到的候选 Revision。
    candidate_memory_revision_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    proposed_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_awareness_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    proposed_stance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    proposed_lifecycle: Mapped[str | None] = mapped_column(String(16), nullable=True)
    evidence_claim_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending / accepted / rejected / stale
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CurrentUserStateRecord(Base):
    """单用户当前阅读上下文，与长期画像和认知记忆分开保存。

    只保存用户此刻的目标、问题和时间预算；有效期过后按未设置处理，
    回退到长期 Profile。不根据浏览行为自动改变。
    """

    __tablename__ = "current_user_state"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    active_goals_json: Mapped[list] = mapped_column(JSON, default=list)
    active_questions_json: Mapped[list] = mapped_column(JSON, default=list)
    focus_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_depth: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exploration_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 状态有效期；为空表示长期有效，过期后 Evaluate 使用保守默认值。
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CurrentUserStateSnapshot(Base):
    """Evaluate 前冻结的不可变阅读上下文快照，后续修改不重写历史分析。"""

    __tablename__ = "current_user_state_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id"), nullable=True, index=True
    )
    # 快照时的状态字段；空字典表示用户没有设置当前状态。
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CognitiveCompareRun(Base):
    """一次 Cognitive Compare 的完整输入、输出与召回上下文。

    候选直接保存 Revision ID（不只逻辑 Memory 或版本数字），保证历史
    Analysis 能精确还原当时使用的 Memory Revision；Memory 后续变化
    不重写本记录。
    """

    __tablename__ = "cognitive_compare_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    current_claim_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    current_memory_candidate_revision_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    historical_memory_candidate_revision_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    # 代码计算的召回上下文，LLM 不能输出或修改。
    retrieval_context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    compare_output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 由确定性代码聚合的 Delta 摘要，不由 LLM 重复填写。
    derived_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="unimplemented")
    # pending / running / completed / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClaimFeedbackEvent(Base):
    """用户对具体 Claim 的轻量知晓 / 立场确认，append-only 保存动作与来源。

    轻量反馈本身不改写 Memory；目标状态先形成，再进入 Memory Match，
    由 Match 决定追加 Confirmation Event、追加 Revision 或生成 Proposal。
    """

    __tablename__ = "claim_feedback_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    content_claim_id: Mapped[str] = mapped_column(
        ForeignKey("content_claims.id"), index=True
    )
    # known / uncertain / None（只表达了立场时为空）
    awareness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # accept / reject / mixed / undecided / not_applicable
    stance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 根因分流（11.5）：memory_* / state_error / retrieval_error / compare_* 等
    root_cause: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClaimCorrection(Base):
    """用户对 primary_relation / claim_role 的高级纠错，append-only。

    原始值与纠正值都保留；Compare 输出和历史 Delta 不变，API 展示
    effective value，纠错只作为 Ground Truth 与未来 Prompt Diagnoser 输入。
    """

    __tablename__ = "claim_corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    content_claim_id: Mapped[str] = mapped_column(
        ForeignKey("content_claims.id"), index=True
    )
    cognitive_compare_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # primary_relation / claim_role
    correction_type: Mapped[str] = mapped_column(String(16))
    original_value: Mapped[str] = mapped_column(String(32))
    corrected_value: Mapped[str] = mapped_column(String(32))
    # 纠正为非 new 关系时可引用的候选 Revision；纠错只保存用户看到的证据。
    matched_memory_revision_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    # complete / incomplete / not_applicable
    evidence_status: Mapped[str] = mapped_column(String(16), default="not_applicable")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
