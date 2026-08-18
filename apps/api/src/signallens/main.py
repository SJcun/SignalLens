"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from math import ceil
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .analysis.claims import load_claim_rows, with_normalized_claims
from .analysis.provider import build_provider_from_settings
from .analysis.schemas import AnalyzeContent, EvaluateForUser
from .analysis.schemas import ContentClaim as ContentClaimContract
from .analysis.sections import SectionIndex, validate_guided_flow
from .auth import (
    create_plugin_key,
    create_session,
    ensure_initial_admin,
    hash_password,
    load_plugin_key,
    load_session,
    remove_bootstrap_password_file,
    revoke_user_sessions,
    verify_password,
)
from .database import SessionLocal, create_schema, get_session
from .memory import (
    MemoryProposalError,
    MemoryRevisionConflict,
    append_memory_revision,
    apply_claim_feedback,
    apply_memory_match,
    apply_proposal_decision,
    run_memory_match,
)
from .models import (
    AdminUser,
    Analysis,
    AnalysisJob,
    AnalysisSchedule,
    ArticleFeedback,
    AuthSession,
    ClaimCorrection,
    ClaimFeedbackEvent,
    CognitiveCompareRun,
    CognitiveMemory,
    CognitiveMemoryRevision,
    Content,
    ContentClaim,
    ContentTranslation,
    CurrentUserStateRecord,
    MemoryChangeProposal,
    MemoryConfirmationEvent,
    PluginApiKey,
    UserProfileRecord,
    utc_now,
)
from .scheduling import DEFAULT_ANALYSIS_WINDOWS, is_within_windows, next_window_start
from .schemas import (
    AnalysisQueueState,
    AnalysisResponse,
    AnalysisScheduleResponse,
    AnalysisScheduleUpdate,
    CalibrationMatrixCell,
    CalibrationStatsResponse,
    CalibrationSuggestionDecision,
    CalibrationSuggestionResponse,
    CaptureAccepted,
    CaptureRequest,
    ChangePasswordRequest,
    ClaimCorrectionResponse,
    ClaimCorrectionUpsert,
    ClaimFeedbackResponse,
    ClaimFeedbackUpsert,
    CognitiveDeltaResponse,
    CompareRunResponse,
    ContentDetailResponse,
    ContentSummaryResponse,
    CurrentUserResponse,
    CurrentUserStateResponse,
    CurrentUserStateUpdate,
    FeedbackResponse,
    FeedbackUpsert,
    GeneratedPluginKeyResponse,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    MemoryConfirmationEventResponse,
    MemoryCreateRequest,
    MemoryDetailResponse,
    MemoryProposalResponse,
    MemoryRevisionAppendRequest,
    MemoryRevisionResponse,
    MemorySummaryResponse,
    MemoryWriteResponse,
    MessageResponse,
    PluginKeyStatusResponse,
    ProfileResponse,
    ProfileUpdate,
    ProposalDecisionRequest,
    TranslationBlockResponse,
    TranslationResponse,
)
from .settings import get_settings
from .translation import (
    TRANSLATION_PROMPT_VERSION,
    align_block_line_ranges,
    content_source_hash,
    detect_source_language,
    split_markdown_blocks,
)
from .urls import normalize_content_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时准备数据库结构和唯一初始管理员。"""

    create_schema()
    ensure_initial_admin()
    yield


settings = get_settings()
app = FastAPI(title="SignalLens API", version="0.1.0", lifespan=lifespan)
RECOMMENDATION_ORDER = {
    "ignore": 0,
    "summary_enough": 1,
    "selective_read": 2,
    "deep_read": 3,
}
CALIBRATION_MIN_FEEDBACK = 20
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_API_PATHS = {"/api/v1/health", "/api/v1/auth/login"}


@app.middleware("http")
async def require_api_authentication(request: Request, call_next):
    """统一保护业务 API，避免新增接口时遗漏鉴权依赖。"""

    path = request.url.path.rstrip("/") or "/"
    needs_auth = (
        path.startswith("/api/v1")
        and path not in PUBLIC_API_PATHS
        and request.method != "OPTIONS"
    )
    if not needs_auth:
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    scheme, separator, raw_token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not raw_token:
        return _unauthorized_response()

    with SessionLocal() as session:
        if raw_token.startswith("sk-sl-"):
            # 插件 Key 采用最小权限，只允许提交采集内容。
            if path != "/api/v1/captures" or request.method != "POST":
                return _unauthorized_response()
            plugin_key = load_plugin_key(session, raw_token)
            if plugin_key is None:
                return _unauthorized_response()
            session.commit()
            request.state.auth_kind = "plugin_key"
            return await call_next(request)

        authenticated = load_session(session, raw_token)
        if authenticated is None:
            return _unauthorized_response()
        user, auth_session = authenticated
        # 请求只携带后续端点需要的稳定标识，不跨数据库会话传递 ORM 对象。
        request.state.auth_user_id = user.id
        request.state.auth_username = user.username
        request.state.must_change_password = user.must_change_password
        request.state.auth_session_id = auth_session.id
        request.state.auth_kind = "admin"
    return await call_next(request)


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """返回无需鉴权的存活状态。"""

    return HealthResponse(status="ok", service="signallens-api")


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    session: Annotated[Session, Depends(get_session)],
) -> LoginResponse:
    """使用唯一管理员账号登录并签发可撤销会话。"""

    user = session.scalar(select(AdminUser).where(AdminUser.username == payload.username.strip()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_token, auth_session = create_session(session, user)
    session.commit()
    return LoginResponse(
        access_token=raw_token,
        username=user.username,
        must_change_password=user.must_change_password,
        expires_at=auth_session.expires_at,
    )


@app.get("/api/v1/auth/me", response_model=CurrentUserResponse)
def current_user(request: Request) -> CurrentUserResponse:
    """返回当前令牌对应的管理员状态。"""

    return CurrentUserResponse(
        username=request.state.auth_username,
        must_change_password=request.state.must_change_password,
    )


@app.post("/api/v1/auth/logout", response_model=MessageResponse)
def logout(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> MessageResponse:
    """只撤销当前设备的会话。"""

    auth_session = session.get(AuthSession, request.state.auth_session_id)
    if auth_session is not None:
        session.delete(auth_session)
        session.commit()
    return MessageResponse(message="已退出登录")


@app.post("/api/v1/auth/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> MessageResponse:
    """修改管理员密码并撤销全部 Web 会话；独立插件 Key 不受影响。"""

    user = session.get(AdminUser, request.state.auth_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="登录账户不存在")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = utc_now()
    revoke_user_sessions(session, user.id)
    session.commit()
    remove_bootstrap_password_file()
    return MessageResponse(message="密码已修改，请重新登录")


@app.get("/api/v1/plugin-key", response_model=PluginKeyStatusResponse)
def get_plugin_key_status(
    session: Annotated[Session, Depends(get_session)],
) -> PluginKeyStatusResponse:
    """返回当前插件 Key 的非敏感状态。"""

    record = session.get(PluginApiKey, "default")
    return PluginKeyStatusResponse(
        configured=record is not None,
        key_prefix=record.key_prefix if record else None,
        created_at=record.created_at if record else None,
        last_used_at=record.last_used_at if record else None,
    )


@app.post("/api/v1/plugin-key", response_model=GeneratedPluginKeyResponse)
def generate_plugin_key(
    session: Annotated[Session, Depends(get_session)],
) -> GeneratedPluginKeyResponse:
    """生成并替换唯一插件 Key，完整值只在本次响应中返回。"""

    raw_key, record = create_plugin_key(session)
    session.commit()
    return GeneratedPluginKeyResponse(
        api_key=raw_key,
        key_prefix=record.key_prefix,
        created_at=record.created_at,
    )


@app.delete("/api/v1/plugin-key", response_model=MessageResponse)
def revoke_plugin_key(
    session: Annotated[Session, Depends(get_session)],
) -> MessageResponse:
    """撤销当前插件 Key，已配置插件会立即无法继续提交。"""

    record = session.get(PluginApiKey, "default")
    if record is not None:
        session.delete(record)
        session.commit()
    return MessageResponse(message="插件 Key 已撤销")


@app.get("/api/v1/memory", response_model=list[MemorySummaryResponse])
def list_memories(session: Annotated[Session, Depends(get_session)]) -> list[MemorySummaryResponse]:
    """返回全部认知记忆的逻辑身份与当前版本。"""

    memories = session.scalars(select(CognitiveMemory).order_by(CognitiveMemory.created_at)).all()
    return [_memory_summary(session, memory) for memory in memories]


@app.get("/api/v1/memory/proposals", response_model=list[MemoryProposalResponse])
def list_memory_proposals(
    session: Annotated[Session, Depends(get_session)],
) -> list[MemoryProposalResponse]:
    """返回等待用户处理的 Memory 修改建议。"""

    proposals = session.scalars(
        select(MemoryChangeProposal)
        .where(MemoryChangeProposal.status == "pending")
        .order_by(MemoryChangeProposal.created_at)
    ).all()
    return [_proposal_response(proposal) for proposal in proposals]


@app.get("/api/v1/memory/{memory_id}", response_model=MemoryDetailResponse)
def get_memory(
    memory_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> MemoryDetailResponse:
    """返回单个 Memory 的完整不可变历史与确认记录。"""

    memory = session.get(CognitiveMemory, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="认知记忆不存在")
    revisions = session.scalars(
        select(CognitiveMemoryRevision)
        .where(CognitiveMemoryRevision.cognitive_memory_id == memory.id)
        .order_by(CognitiveMemoryRevision.version.desc())
    ).all()
    events = session.scalars(
        select(MemoryConfirmationEvent)
        .where(MemoryConfirmationEvent.cognitive_memory_id == memory.id)
        .order_by(MemoryConfirmationEvent.created_at.desc())
    ).all()
    return MemoryDetailResponse(
        **_memory_summary(session, memory).model_dump(),
        revisions=[_memory_revision_response(item) for item in revisions],
        confirmation_events=[
            MemoryConfirmationEventResponse(
                id=item.id,
                confirmation_type=item.confirmation_type,
                source_type=item.source_type,
                content_claim_id=item.content_claim_id,
                source_feedback_id=item.source_feedback_id,
                source_proposal_id=item.source_proposal_id,
                created_at=item.created_at,
            )
            for item in events
        ],
    )


@app.post("/api/v1/memory", response_model=MemoryWriteResponse)
def create_memory_entry(
    payload: MemoryCreateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> MemoryWriteResponse:
    """手工录入认知；CREATE 前先执行 Memory Match，不能直接新建。"""

    match = run_memory_match(
        session,
        build_provider_from_settings(),
        statement=payload.statement,
        topics=payload.topics,
        entities=payload.entities,
    )
    outcome, memory_id, proposal_id = apply_memory_match(
        session,
        match,
        statement=payload.statement,
        target_awareness=payload.awareness_state,
        target_stance=payload.stance,
        target_lifecycle=payload.lifecycle,
        source_type="manual",
        confirmation_type="awareness_confirmed",
        topics=payload.topics,
        entities=payload.entities,
    )
    session.commit()
    return _memory_write_response(session, outcome, memory_id, proposal_id, match)


@app.post(
    "/api/v1/memory/{memory_id}/revisions",
    response_model=MemoryWriteResponse,
)
def append_memory_revision_entry(
    memory_id: str,
    payload: MemoryRevisionAppendRequest,
    session: Annotated[Session, Depends(get_session)],
) -> MemoryWriteResponse:
    """为已有 Memory 追加 Revision；期望版本不匹配时返回明确冲突。"""

    memory = session.get(CognitiveMemory, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="认知记忆不存在")
    if memory.current_revision_id is None:
        raise HTTPException(status_code=409, detail="认知记忆没有当前版本")

    current = session.get(CognitiveMemoryRevision, memory.current_revision_id)
    if current is None:
        raise HTTPException(status_code=409, detail="认知记忆当前版本缺失")
    if current.id != payload.expected_current_revision_id:
        raise HTTPException(
            status_code=409,
            detail="当前版本已变化，请基于最新版本重新确认",
        )
    try:
        append_memory_revision(
            session,
            memory.id,
            statement=payload.statement or current.statement,
            awareness_state=payload.awareness_state or current.awareness_state,
            stance=payload.stance or current.stance,
            lifecycle=payload.lifecycle or current.lifecycle,
            confidence=payload.confidence or current.confidence,
            source_type="manual",
            expected_current_revision_id=current.id,
            topics=list(current.topics_json),
            entities=list(current.entities_json),
        )
    except MemoryRevisionConflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return MemoryWriteResponse(
        outcome="revised",
        memory=_memory_summary(session, memory),
        proposal_id=None,
        match_source="none",
        reason="已按用户修改追加新版本",
    )


@app.post(
    "/api/v1/memory/proposals/{proposal_id}/decision",
    response_model=MemoryProposalResponse,
)
def decide_memory_proposal(
    proposal_id: str,
    payload: ProposalDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> MemoryProposalResponse:
    """接受或拒绝 Memory 修改建议；只有 accepted 才能改变正式状态。"""

    existing = session.get(MemoryChangeProposal, proposal_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="修改建议不存在")
    try:
        proposal, _outcome, _memory_id = apply_proposal_decision(
            session,
            build_provider_from_settings(),
            proposal_id=proposal_id,
            decision=payload.decision,
            merge_memory_id=payload.merge_memory_id,
        )
    except MemoryRevisionConflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MemoryProposalError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return _proposal_response(proposal)


@app.get("/api/v1/profile", response_model=ProfileResponse)
def get_profile(session: Annotated[Session, Depends(get_session)]) -> ProfileResponse:
    """返回当前问卷画像；未填写时提供可直接编辑的默认值。"""

    return _profile_response(_get_or_create_profile(session))


@app.put("/api/v1/profile", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> ProfileResponse:
    """保存显式问卷答案，不从单篇文章反馈自动推断画像。"""

    profile = _get_or_create_profile(session)
    profile.focus_topics_json = payload.focus_topics
    profile.known_topics_json = [item.model_dump(mode="json") for item in payload.known_topics]
    profile.reading_goals_json = payload.reading_goals
    profile.preferred_depth = payload.preferred_depth
    profile.time_budget_minutes = payload.time_budget_minutes
    profile.exploration_level = payload.exploration_level
    profile.evaluation_mode = payload.evaluation_mode
    profile.questionnaire_completed_at = profile.questionnaire_completed_at or utc_now()
    profile.updated_at = utc_now()
    session.commit()
    return _profile_response(profile)


@app.get("/api/v1/user-state", response_model=CurrentUserStateResponse)
def get_user_state(
    session: Annotated[Session, Depends(get_session)],
) -> CurrentUserStateResponse:
    """返回当前阅读状态；未编辑时提供可直接填写的默认值。"""

    return _user_state_response(_get_or_create_user_state(session))


@app.put("/api/v1/user-state", response_model=CurrentUserStateResponse)
def update_user_state(
    payload: CurrentUserStateUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> CurrentUserStateResponse:
    """保存用户显式编辑的当前阅读上下文，不根据浏览行为自动推断。"""

    record = _get_or_create_user_state(session)
    record.active_goals_json = payload.active_goals
    record.active_questions_json = payload.active_questions
    record.focus_context = payload.focus_context
    record.available_minutes = payload.available_minutes
    record.preferred_depth = payload.preferred_depth
    record.exploration_level = payload.exploration_level
    record.valid_until = payload.valid_until
    record.updated_at = utc_now()
    session.commit()
    return _user_state_response(record)


@app.get("/api/v1/analysis-schedule", response_model=AnalysisScheduleResponse)
def get_analysis_schedule(
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisScheduleResponse:
    """返回 AI 整理总开关、时段和当前队列状态。"""

    return _schedule_response(session, _get_or_create_analysis_schedule(session))


@app.put("/api/v1/analysis-schedule", response_model=AnalysisScheduleResponse)
def update_analysis_schedule(
    payload: AnalysisScheduleUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisScheduleResponse:
    """原子保存总开关与每日时段，关闭时立即恢复提交即分析。"""

    schedule = _get_or_create_analysis_schedule(session)
    schedule.enabled = payload.enabled
    schedule.windows_json = [item.model_dump(mode="json") for item in payload.windows]
    schedule.updated_at = utc_now()
    session.commit()
    return _schedule_response(session, schedule)


@app.post(
    "/api/v1/captures",
    response_model=CaptureAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_capture(
    payload: CaptureRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CaptureAccepted:
    """幂等保存手动采集内容，并创建一条待分析任务。"""

    canonical_url = normalize_content_url(
        str(payload.source.canonical_url or payload.source.url)
    )
    existing = session.scalar(
        select(Content).where(
            (Content.capture_id == payload.capture_id)
            | (
                (Content.source_type == payload.source.type)
                & (Content.canonical_url == canonical_url)
            )
        )
    )
    if existing:
        # 重复提交更新最新正文快照，但内容本身仍保持一条记录。
        existing.source_url = str(payload.source.url)
        existing.canonical_url = canonical_url
        existing.title = payload.source.title
        existing.author = payload.source.author
        existing.markdown = payload.document.text
        existing.capture_quality = payload.capture.quality.level
        existing.capture_payload_json = payload.model_dump(mode="json")
        analysis = session.scalar(
            select(Analysis).where(Analysis.content_id == existing.id).order_by(Analysis.created_at.desc())
        )
        if analysis is None:
            raise HTTPException(status_code=409, detail="采集记录存在，但分析任务缺失")
        session.commit()
        return _accepted(session, existing, analysis)

    if payload.capture.quality.level == "failed":
        raise HTTPException(status_code=422, detail="提取失败的内容不能进入分析")

    content = Content(
        capture_id=payload.capture_id,
        source_type=payload.source.type,
        source_url=str(payload.source.url),
        canonical_url=canonical_url,
        capture_mode=payload.capture.mode,
        title=payload.source.title,
        author=payload.source.author,
        markdown=payload.document.text,
        capture_quality=payload.capture.quality.level,
        capture_payload_json=payload.model_dump(mode="json"),
    )
    analysis = Analysis(content=content)
    job = AnalysisJob(analysis=analysis)
    session.add_all([content, analysis, job])
    session.commit()
    return _accepted(session, content, analysis)


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisResponse:
    """返回分析状态和已完成的结构化结果。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return _analysis_response(session, analysis)


@app.post(
    "/api/v1/analyses/{analysis_id}/run-now",
    response_model=CaptureAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_analysis_now(
    analysis_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CaptureAccepted:
    """持久化用户的立即整理要求，后续所有阶段绕过时段门禁。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    if analysis.status not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="只有等待或进行中的任务可以立即整理")
    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
    content = session.get(Content, analysis.content_id)
    if job is None or content is None:
        raise HTTPException(status_code=409, detail="分析任务关联数据缺失")

    job.immediate_requested_at = job.immediate_requested_at or utc_now()
    session.commit()
    return _accepted(session, content, analysis)


@app.post(
    "/api/v1/analyses/{analysis_id}/retry",
    response_model=CaptureAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_analysis(
    analysis_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CaptureAccepted:
    """清理失败阶段结果，并把原分析任务重新放回待处理队列。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    if analysis.status != "failed":
        raise HTTPException(status_code=409, detail="只有失败的分析任务可以重新执行")

    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
    content = session.get(Content, analysis.content_id)
    if job is None or content is None:
        raise HTTPException(status_code=409, detail="分析任务关联数据缺失")

    # 失败时可能已经保存了前序阶段；重跑必须从同一内容快照完整开始，
    # 防止新 Prompt 与旧阶段结果混用。章节清单同样在重新领取时生成。
    analysis.status = "pending"
    analysis.triage_json = None
    analysis.content_analysis_json = None
    analysis.personal_evaluation_json = None
    analysis.source_hash = None
    analysis.section_index_json = None
    analysis.model = None
    analysis.prompt_version = "unimplemented"
    analysis.completed_at = None
    job.stage = "triage"
    job.status = "pending"
    job.last_error = None
    job.immediate_requested_at = None
    session.commit()
    return _accepted(session, content, analysis)


@app.get("/api/v1/analyses/{analysis_id}/compare", response_model=CompareRunResponse)
def get_compare_run(
    analysis_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CompareRunResponse:
    """返回某次分析的 Compare 完整输入、召回上下文与结果。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    run = (
        session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
        if analysis.cognitive_compare_run_id
        else None
    )
    if run is None:
        raise HTTPException(status_code=404, detail="该分析没有可用的 Compare 运行记录")
    return _compare_run_response(session, run)


@app.post(
    "/api/v1/analyses/{analysis_id}/retry-compare",
    response_model=MessageResponse,
)
def retry_compare(
    analysis_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> MessageResponse:
    """单独重试失败的 Compare；不重跑 Evaluate，不改写历史 Delta。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    if analysis.status == "completed":
        raise HTTPException(status_code=409, detail="已完成的分析不能重试 Compare")
    run = (
        session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
        if analysis.cognitive_compare_run_id
        else None
    )
    if run is None:
        raise HTTPException(status_code=409, detail="没有可重试的 Compare 运行")
    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
    if job is None:
        raise HTTPException(status_code=409, detail="分析队列任务缺失")

    run.status = "pending"
    run.compare_output_json = None
    run.derived_summary_json = None
    run.last_error = None
    run.completed_at = None
    job.stage = "compare"
    job.status = "pending"
    job.last_error = None
    analysis.status = "pending"
    session.commit()
    return MessageResponse(message="Compare 已重新排队")


@app.post(
    "/api/v1/analyses/{analysis_id}/claims/{claim_id}/feedback",
    response_model=ClaimFeedbackResponse,
)
def submit_claim_feedback(
    analysis_id: str,
    claim_id: str,
    payload: ClaimFeedbackUpsert,
    session: Annotated[Session, Depends(get_session)],
) -> ClaimFeedbackResponse:
    """对具体 Claim 提交知晓 / 立场确认；目标状态先进入 Memory Match。"""

    claim = _load_analysis_claim(session, analysis_id, claim_id)
    event = ClaimFeedbackEvent(
        analysis_id=analysis_id,
        content_claim_id=claim.id,
        awareness=payload.awareness,
        stance=payload.stance,
        root_cause=payload.root_cause,
    )
    session.add(event)
    session.flush()
    outcome, memory_id, proposal_id, match = apply_claim_feedback(
        session,
        build_provider_from_settings(),
        content_claim_id=claim.id,
        awareness=payload.awareness,
        stance=payload.stance,
        source_feedback_id=event.id,
        confirmation_type=payload.confirmation_type,
    )
    session.commit()
    return ClaimFeedbackResponse(
        outcome=outcome,
        memory_id=memory_id,
        proposal_id=proposal_id,
        match_source=match.match_source,
        reason=match.reason,
    )


@app.post(
    "/api/v1/analyses/{analysis_id}/claims/{claim_id}/correction",
    response_model=ClaimCorrectionResponse,
)
def submit_claim_correction(
    analysis_id: str,
    claim_id: str,
    payload: ClaimCorrectionUpsert,
    session: Annotated[Session, Depends(get_session)],
) -> ClaimCorrectionResponse:
    """提交 primary_relation / claim_role 高级纠错，原始值与纠正值都保留。"""

    claim = _load_analysis_claim(session, analysis_id, claim_id)
    analysis = session.get(Analysis, analysis_id)
    run = (
        session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
        if analysis is not None and analysis.cognitive_compare_run_id
        else None
    )
    original_value = _correction_original_value(claim, run, payload.correction_type)
    if original_value == payload.corrected_value:
        raise HTTPException(status_code=409, detail="纠正值与原始值相同")

    evidence_status = "not_applicable"
    matched_ids = list(payload.matched_memory_revision_ids)
    if payload.correction_type == "primary_relation":
        if payload.corrected_value not in {
            "duplicate",
            "extends",
            "complements",
            "contradicts",
            "updates",
            "new",
        }:
            raise HTTPException(status_code=422, detail="无效的认知关系")
        if payload.corrected_value == "new":
            matched_ids = []
            evidence_status = "not_applicable"
        elif run is not None:
            allowed = set(run.current_memory_candidate_revision_ids_json) | set(
                run.historical_memory_candidate_revision_ids_json
            )
            if matched_ids and not set(matched_ids) <= allowed:
                raise HTTPException(status_code=422, detail="证据必须来自本次候选集合")
            if set(matched_ids) <= allowed and matched_ids:
                evidence_status = "complete"
            else:
                evidence_status = "incomplete"
        else:
            matched_ids = []
            evidence_status = "incomplete"
    else:
        if payload.corrected_value not in {"core", "supporting", "detail"}:
            raise HTTPException(status_code=422, detail="无效的 Claim 角色")
        matched_ids = []

    correction = ClaimCorrection(
        analysis_id=analysis_id,
        content_claim_id=claim.id,
        cognitive_compare_run_id=run.id if run else None,
        correction_type=payload.correction_type,
        original_value=original_value,
        corrected_value=payload.corrected_value,
        matched_memory_revision_ids_json=matched_ids,
        evidence_status=evidence_status,
        reason=payload.reason,
    )
    session.add(correction)
    session.commit()
    return _claim_correction_response(correction)


@app.put(
    "/api/v1/analyses/{analysis_id}/feedback",
    response_model=FeedbackResponse,
)
def upsert_feedback(
    analysis_id: str,
    payload: FeedbackUpsert,
    session: Annotated[Session, Depends(get_session)],
) -> FeedbackResponse:
    """新增或更新阅读评价，并冻结提交时的 AI 结果用于后续校准。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    if analysis.status != "completed":
        raise HTTPException(status_code=409, detail="分析完成后才能提交阅读评价")

    feedback = session.scalar(
        select(ArticleFeedback).where(ArticleFeedback.analysis_id == analysis.id)
    )
    evaluation = analysis.personal_evaluation_json or {}
    ai_recommendation = (
        feedback.ai_recommendation
        if feedback is not None
        else evaluation.get("recommendation")
        or (
            "ignore"
            if (analysis.triage_json or {}).get("decision") == "ignore"
            else None
        )
    )
    if ai_recommendation not in RECOMMENDATION_ORDER:
        raise HTTPException(status_code=409, detail="当前分析没有可比较的阅读建议")

    # 用户只提交自己认为合适的等级，偏差方向由固定等级顺序统一计算。
    ai_level = RECOMMENDATION_ORDER[ai_recommendation]
    preferred_level = RECOMMENDATION_ORDER[payload.preferred_recommendation]
    recommendation_accuracy = (
        "too_high"
        if ai_level > preferred_level
        else "too_low" if ai_level < preferred_level else "accurate"
    )
    if feedback is None:
        feedback = ArticleFeedback(
            content_id=analysis.content_id,
            analysis_id=analysis.id,
            preferred_recommendation=payload.preferred_recommendation,
            recommendation_accuracy=recommendation_accuracy,
            time_worthwhile=payload.time_worthwhile,
            new_knowledge=payload.new_knowledge,
            summary_quality=payload.summary_quality,
            key_takeaway=payload.key_takeaway,
            # 分诊阶段直接忽略时不会生成个人评估，也要保留 AI 的原始建议，
            # 否则无法统计用户认为值得阅读的漏判。
            ai_recommendation=ai_recommendation,
            model=analysis.model,
            prompt_version=analysis.prompt_version,
            analysis_snapshot_json=_analysis_snapshot(analysis),
        )
        session.add(feedback)
    else:
        # 更新人工评价，但保留首次提交时冻结的 AI 快照和版本。
        feedback.preferred_recommendation = payload.preferred_recommendation
        feedback.recommendation_accuracy = recommendation_accuracy
        feedback.time_worthwhile = payload.time_worthwhile
        feedback.new_knowledge = payload.new_knowledge
        feedback.summary_quality = payload.summary_quality
        feedback.key_takeaway = payload.key_takeaway
        feedback.updated_at = utc_now()
    session.commit()
    return _feedback_response(feedback)


@app.get("/api/v1/calibration/stats", response_model=CalibrationStatsResponse)
def calibration_stats(
    session: Annotated[Session, Depends(get_session)],
) -> CalibrationStatsResponse:
    """汇总人工反馈，重点暴露推荐偏差和高价值误杀。"""

    profile = _get_or_create_profile(session)
    feedbacks = session.scalars(select(ArticleFeedback)).all()
    eligible_feedbacks = [
        item
        for item in feedbacks
        if item.ai_recommendation in RECOMMENDATION_ORDER
        and item.preferred_recommendation in RECOMMENDATION_ORDER
    ]
    accurate = sum(item.recommendation_accuracy == "accurate" for item in feedbacks)
    too_high = sum(item.recommendation_accuracy == "too_high" for item in feedbacks)
    too_low = sum(item.recommendation_accuracy == "too_low" for item in feedbacks)
    confusion_counts: dict[tuple[str, str], int] = {}
    adjacent_error_count = 0
    major_error_count = 0
    for item in eligible_feedbacks:
        key = (item.ai_recommendation, item.preferred_recommendation)
        confusion_counts[key] = confusion_counts.get(key, 0) + 1
        distance = abs(
            RECOMMENDATION_ORDER[item.ai_recommendation]
            - RECOMMENDATION_ORDER[item.preferred_recommendation]
        )
        adjacent_error_count += distance == 1
        major_error_count += distance >= 2
    completed = int(
        session.scalar(select(func.count()).select_from(Analysis).where(Analysis.status == "completed"))
        or 0
    )
    return CalibrationStatsResponse(
        evaluation_mode=profile.evaluation_mode,
        questionnaire_completed=profile.questionnaire_completed_at is not None,
        completed_analyses=completed,
        feedback_count=len(feedbacks),
        accurate_count=accurate,
        too_high_count=too_high,
        too_low_count=too_low,
        accuracy_rate=round(accurate / len(feedbacks) * 100, 1) if feedbacks else None,
        summary_issue_count=sum(
            item.summary_quality in {"omission", "misleading"} for item in feedbacks
        ),
        high_value_miss_count=sum(
            item.ai_recommendation == "ignore"
            and (item.recommendation_accuracy == "too_low" or item.time_worthwhile == "yes")
            for item in feedbacks
        ),
        feedback_needed=max(0, CALIBRATION_MIN_FEEDBACK - len(eligible_feedbacks)),
        adjacent_error_count=adjacent_error_count,
        major_error_count=major_error_count,
        confusion_matrix=[
            CalibrationMatrixCell(
                ai_recommendation=ai_recommendation,
                user_recommendation=user_recommendation,
                count=count,
            )
            for (ai_recommendation, user_recommendation), count in sorted(
                confusion_counts.items(),
                key=lambda item: (
                    RECOMMENDATION_ORDER[item[0][0]],
                    RECOMMENDATION_ORDER[item[0][1]],
                ),
            )
        ],
        suggestions=_calibration_suggestions(
            eligible_feedbacks,
            profile.calibration_decisions_json or {},
        ),
    )


@app.put(
    "/api/v1/calibration/suggestions/{suggestion_id}",
    response_model=CalibrationSuggestionResponse,
)
def decide_calibration_suggestion(
    suggestion_id: str,
    payload: CalibrationSuggestionDecision,
    session: Annotated[Session, Depends(get_session)],
) -> CalibrationSuggestionResponse:
    """记录用户对候选规则的决定，但不自动修改画像或模型 Prompt。"""

    profile = _get_or_create_profile(session)
    feedbacks = session.scalars(select(ArticleFeedback)).all()
    suggestions = _calibration_suggestions(
        [
            item
            for item in feedbacks
            if item.ai_recommendation in RECOMMENDATION_ORDER
            and item.preferred_recommendation in RECOMMENDATION_ORDER
        ],
        profile.calibration_decisions_json or {},
    )
    suggestion = next((item for item in suggestions if item.id == suggestion_id), None)
    if suggestion is None:
        raise HTTPException(status_code=409, detail="当前反馈尚不足以支持这条校准建议")

    decisions = dict(profile.calibration_decisions_json or {})
    decisions[suggestion_id] = payload.decision
    profile.calibration_decisions_json = decisions
    profile.updated_at = utc_now()
    session.commit()
    return suggestion.model_copy(update={"status": payload.decision})


@app.get("/api/v1/contents", response_model=list[ContentSummaryResponse])
def list_contents(
    session: Annotated[Session, Depends(get_session)],
    limit: int = 50,
) -> list[ContentSummaryResponse]:
    """按采集时间倒序返回内容及其最新一次分析状态。"""

    safe_limit = max(1, min(limit, 200))
    latest_analysis_id = (
        select(Analysis.id)
        .where(Analysis.content_id == Content.id)
        .order_by(Analysis.created_at.desc())
        .limit(1)
        .correlate(Content)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Content, Analysis, AnalysisJob, ArticleFeedback)
        .join(Analysis, Analysis.id == latest_analysis_id)
        .join(AnalysisJob, AnalysisJob.analysis_id == Analysis.id)
        .outerjoin(ArticleFeedback, ArticleFeedback.analysis_id == Analysis.id)
        .order_by(Content.created_at.desc())
        .limit(safe_limit)
    ).all()
    return [
        _content_summary(session, content, analysis, job, feedback)
        for content, analysis, job, feedback in rows
    ]


@app.get("/api/v1/contents/{content_id}", response_model=ContentDetailResponse)
def get_content(
    content_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> ContentDetailResponse:
    """返回原始 Markdown 和最新分析，供内容详情页展示。"""

    content = session.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="内容不存在")
    analysis = session.scalar(
        select(Analysis)
        .where(Analysis.content_id == content.id)
        .order_by(Analysis.created_at.desc())
    )
    if analysis is None:
        raise HTTPException(status_code=409, detail="内容存在，但分析任务缺失")
    feedback = session.scalar(
        select(ArticleFeedback).where(ArticleFeedback.analysis_id == analysis.id)
    )
    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
    if job is None:
        raise HTTPException(status_code=409, detail="内容存在，但分析队列任务缺失")
    translation = session.scalar(
        select(ContentTranslation).where(
            ContentTranslation.content_id == content.id,
            ContentTranslation.target_language == "zh-CN",
        )
    )
    current_source_hash = content_source_hash(content.markdown)
    summary = _content_summary(session, content, analysis, job, feedback)
    claim_rows = load_claim_rows(session, analysis.id)
    delta = _cognitive_delta(session, analysis)
    return ContentDetailResponse(
        **summary.model_dump(),
        markdown=content.markdown,
        source_language=detect_source_language(content.markdown),
        translation=(
            _translation_response(translation, content.markdown)
            if translation and translation.source_hash == current_source_hash
            else None
        ),
        triage=analysis.triage_json,
        content_analysis=with_normalized_claims(analysis.content_analysis_json),
        personal_evaluation=analysis.personal_evaluation_json,
        feedback=_feedback_response(feedback) if feedback else None,
        section_index=(
            SectionIndex.model_validate(analysis.section_index_json)
            if analysis.section_index_json and analysis.source_hash == current_source_hash
            else None
        ),
        guided_flow_available=_guided_flow_available(analysis, feedback, current_source_hash),
        claims=_claim_response_rows(claim_rows) if claim_rows else None,
        cognitive_delta=delta,
        retrieval_context_status=analysis.retrieval_context_status,
    )


def _guided_flow_available(
    analysis: Analysis,
    feedback: ArticleFeedback | None,
    current_source_hash: str,
) -> bool:
    """判断详情页是否满足顺序式引导阅读流的全部启用条件。

    引用、覆盖范围或正文哈希任一校验失败时都返回 False，正文整体退回
    完整原文模式；校验失败不影响文章级建议、摘要和历史阅读计划列表。
    """

    if analysis.status != "completed":
        return False
    if analysis.source_hash != current_source_hash or not analysis.section_index_json:
        return False
    try:
        content_analysis = AnalyzeContent.model_validate(
            with_normalized_claims(analysis.content_analysis_json)
        )
        evaluation = EvaluateForUser.model_validate(analysis.personal_evaluation_json)
        section_index = SectionIndex.model_validate(analysis.section_index_json)
    except (TypeError, ValueError):
        # 旧版本 JSON 或损坏数据按无引导流处理，不阻塞详情页读取。
        return False
    if evaluation.recommendation != "selective_read":
        return False
    # 用户把本次建议修正为其他文章级动作后，不再自动应用旧章节计划。
    if (
        feedback is not None
        and feedback.preferred_recommendation is not None
        and feedback.preferred_recommendation != "selective_read"
    ):
        return False
    return (
        validate_guided_flow(
            section_index,
            content_analysis.content_map,
            evaluation.reading_plan,
        )
        is None
    )


@app.post(
    "/api/v1/contents/{content_id}/translation",
    response_model=TranslationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_or_retry_translation(
    content_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> TranslationResponse:
    """幂等创建正文翻译；失败重试只继续尚未完成的内容块。"""

    content = session.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="内容不存在")

    source_language = detect_source_language(content.markdown)
    if source_language.lower().startswith("zh"):
        raise HTTPException(status_code=409, detail="当前正文已经是中文，无需翻译")
    if not source_language.lower().startswith("en"):
        raise HTTPException(status_code=409, detail="当前版本只支持英文正文翻译")

    source_hash = content_source_hash(content.markdown)
    translation = session.scalar(
        select(ContentTranslation).where(
            ContentTranslation.content_id == content.id,
            ContentTranslation.target_language == "zh-CN",
        )
    )
    if translation is None:
        blocks = split_markdown_blocks(content.markdown)
        total_blocks = sum(block["translatable"] for block in blocks)
        if total_blocks == 0:
            raise HTTPException(status_code=422, detail="正文中没有可翻译的文字")
        translation = ContentTranslation(
            content_id=content.id,
            source_language=source_language,
            target_language="zh-CN",
            source_hash=source_hash,
            blocks_json=blocks,
            total_blocks=total_blocks,
        )
        session.add(translation)
    elif translation.source_hash != source_hash:
        # 正文重新采集后旧译文不能继续展示，也不能与新快照混合。
        blocks = split_markdown_blocks(content.markdown)
        total_blocks = sum(block["translatable"] for block in blocks)
        if total_blocks == 0:
            raise HTTPException(status_code=422, detail="正文中没有可翻译的文字")
        translation.source_language = source_language
        translation.source_hash = source_hash
        translation.status = "pending"
        translation.blocks_json = blocks
        translation.completed_blocks = 0
        translation.total_blocks = total_blocks
        translation.attempts = 0
        translation.model = None
        translation.prompt_version = "unimplemented"
        translation.last_error = None
        translation.completed_at = None
    elif translation.status == "failed":
        translation.status = "pending"
        translation.last_error = None
        translation.completed_at = None

    session.commit()
    return _translation_response(translation, content.markdown)


def _content_summary(
    session: Session,
    content: Content,
    analysis: Analysis,
    job: AnalysisJob,
    feedback: ArticleFeedback | None = None,
) -> ContentSummaryResponse:
    """从持久化 JSON 中安全提取 Inbox 所需的少量展示字段。"""

    content_analysis = analysis.content_analysis_json or {}
    personal_evaluation = analysis.personal_evaluation_json or {}
    triage = analysis.triage_json or {}
    ai_recommendation = personal_evaluation.get("recommendation") or (
        "ignore" if triage.get("decision") == "ignore" else None
    )
    user_recommendation = feedback.preferred_recommendation if feedback else None
    return ContentSummaryResponse(
        id=content.id,
        title=content.title,
        author=content.author,
        source_url=content.source_url,
        source_type=content.source_type,
        capture_quality=content.capture_quality,
        created_at=content.created_at,
        analysis_id=analysis.id,
        analysis_status=analysis.status,
        one_sentence_summary=content_analysis.get("one_sentence_summary"),
        recommendation=user_recommendation or ai_recommendation,
        ai_recommendation=ai_recommendation,
        user_recommendation=user_recommendation,
        discovery_type=personal_evaluation.get("discovery_type") or triage.get("discovery_type"),
        queue=_queue_state(session, analysis, job),
        delta_summary=_delta_summary_for(session, analysis),
    )


def _delta_summary_for(session: Session, analysis: Analysis) -> dict | None:
    """提取 Inbox 使用的简短认知差异摘要，不携带完整关系列表。"""

    if not analysis.cognitive_compare_run_id:
        return None
    run = session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
    if run is None or run.status != "completed" or not run.derived_summary_json:
        return None
    summary = run.derived_summary_json
    return {
        "cognitive_gain_count": len(summary.get("cognitive_gain_claim_ids") or []),
        "known_duplicate_count": len(summary.get("known_duplicate_claim_ids") or []),
        "retrieval_context_status": summary.get("retrieval_context_status"),
    }


def _translation_response(translation: ContentTranslation, markdown: str) -> TranslationResponse:
    """把内部断点字段转换为详情页需要的安全翻译响应。

    markdown 用于为旧译文块按位置补齐行号；块与当前正文不一致时，
    行号保持为空，引导流退回逐节原文展示。
    """

    blocks = align_block_line_ranges(markdown, translation.blocks_json)
    return TranslationResponse(
        id=translation.id,
        status=translation.status,
        source_language=translation.source_language,
        target_language="zh-CN",
        completed_blocks=translation.completed_blocks,
        total_blocks=translation.total_blocks,
        blocks=[
            TranslationBlockResponse(
                id=block["id"],
                kind=block["kind"],
                source_markdown=block["source_markdown"],
                translated_markdown=block.get("translated_markdown"),
                shared=not block["translatable"],
                start_line=block.get("start_line"),
                end_line=block.get("end_line"),
            )
            for block in blocks
        ],
        model=translation.model,
        prompt_version=translation.prompt_version or TRANSLATION_PROMPT_VERSION,
        last_error=translation.last_error,
        created_at=translation.created_at,
        completed_at=translation.completed_at,
    )


def _calibration_suggestions(
    feedbacks: list[ArticleFeedback],
    decisions: dict,
) -> list[CalibrationSuggestionResponse]:
    """从足量真实反馈中提取候选规则，不自动改写画像或 Prompt。"""

    if len(feedbacks) < CALIBRATION_MIN_FEEDBACK:
        return []

    threshold = max(5, ceil(len(feedbacks) * 0.25))
    too_high = sum(item.recommendation_accuracy == "too_high" for item in feedbacks)
    too_low = sum(item.recommendation_accuracy == "too_low" for item in feedbacks)
    high_value_miss = sum(
        item.ai_recommendation == "ignore"
        and item.preferred_recommendation != "ignore"
        for item in feedbacks
    )
    summary_issues = sum(
        item.summary_quality in {"omission", "misleading"} for item in feedbacks
    )
    candidates: list[tuple[str, str, str, str]] = []

    if too_high >= threshold and too_low >= threshold:
        candidates.append(
            (
                "split_recommendation_context",
                "按场景拆分阅读投入标准",
                f"{too_high} 次建议偏高，同时有 {too_low} 次建议偏低。",
                "不要整体调高或调低阅读投入；分别检查知识重复、证据强度和探索价值。",
            )
        )
    elif too_high >= threshold and too_high >= too_low * 1.5:
        candidates.append(
            (
                "reduce_over_recommendation",
                "降低过度投入建议",
                f"{len(feedbacks)} 条有效反馈中有 {too_high} 次建议偏高。",
                "知识重叠高且没有明确新增信息时，阅读投入最高为“摘要即可”。",
            )
        )
    elif too_low >= threshold and too_low >= too_high * 1.5:
        candidates.append(
            (
                "protect_under_recommendation",
                "减少低估高价值内容",
                f"{len(feedbacks)} 条有效反馈中有 {too_low} 次建议偏低。",
                "存在关键新知识、强反方观点或高探索价值时，不应仅因主题低相关而降低投入。",
            )
        )

    if high_value_miss >= max(3, ceil(len(feedbacks) * 0.15)):
        candidates.append(
            (
                "protect_ignore_boundary",
                "收紧“可以忽略”的边界",
                f"有 {high_value_miss} 篇被建议忽略的内容被用户修正为值得阅读。",
                "只有低内在价值且低探索价值时才建议忽略；不确定时至少保留为摘要即可。",
            )
        )
    if summary_issues >= threshold:
        candidates.append(
            (
                "preserve_summary_evidence",
                "加强摘要的证据与限制保留",
                f"有 {summary_issues} 条反馈指出摘要存在遗漏或误导。",
                "摘要必须保留原文的重要限制、反方观点和未验证主张。",
            )
        )

    return [
        CalibrationSuggestionResponse(
            id=suggestion_id,
            title=title,
            evidence=evidence,
            proposed_rule=proposed_rule,
            status=decisions.get(suggestion_id, "pending"),
        )
        for suggestion_id, title, evidence, proposed_rule in candidates
    ]


def _accepted(session: Session, content: Content, analysis: Analysis) -> CaptureAccepted:
    """统一构造异步采集响应。"""

    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
    if job is None:
        raise HTTPException(status_code=409, detail="分析队列任务缺失")
    return CaptureAccepted(
        content_id=content.id,
        analysis_id=analysis.id,
        status=analysis.status,
        detail_url=f"/contents/{content.id}",
        queue=_queue_state(session, analysis, job),
    )


def _analysis_response(session: Session, analysis: Analysis) -> AnalysisResponse:
    """统一构造分析状态响应并触发结构化结果校验。"""

    job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis.id))
    if job is None:
        raise HTTPException(status_code=409, detail="分析队列任务缺失")
    return AnalysisResponse(
        id=analysis.id,
        content_id=analysis.content_id,
        status=analysis.status,
        triage=analysis.triage_json,
        content_analysis=analysis.content_analysis_json,
        personal_evaluation=analysis.personal_evaluation_json,
        retrieval_context_status=analysis.retrieval_context_status,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        queue=_queue_state(session, analysis, job),
    )


def _get_or_create_analysis_schedule(session: Session) -> AnalysisSchedule:
    """读取全局整理设置；首次访问保持现有的立即分析行为。"""

    schedule = session.get(AnalysisSchedule, "default")
    if schedule is None:
        schedule = AnalysisSchedule(
            id="default",
            enabled=False,
            windows_json=[dict(item) for item in DEFAULT_ANALYSIS_WINDOWS],
        )
        session.add(schedule)
        session.commit()
    return schedule


def _schedule_response(
    session: Session,
    schedule: AnalysisSchedule,
) -> AnalysisScheduleResponse:
    """计算当前是否放行及下一窗口，时间统一从 UTC 转换。"""

    now = utc_now()
    windows = list(schedule.windows_json)
    in_window = is_within_windows(now, windows)
    currently_allowed = not schedule.enabled or in_window
    scheduled_job_count = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisJob)
            .where(
                AnalysisJob.status == "pending",
                AnalysisJob.immediate_requested_at.is_(None),
            )
        )
        or 0
    )
    return AnalysisScheduleResponse(
        enabled=schedule.enabled,
        windows=windows,
        currently_allowed=currently_allowed,
        next_window_start=(
            None if currently_allowed else next_window_start(now, windows)
        ),
        scheduled_job_count=scheduled_job_count,
        updated_at=schedule.updated_at,
    )


def _queue_state(
    session: Session,
    analysis: Analysis,
    job: AnalysisJob,
) -> AnalysisQueueState:
    """从任务覆盖标记和全局设置推导用户可见的等待原因。"""

    schedule = session.get(AnalysisSchedule, "default")
    now = utc_now()
    windows = (
        list(schedule.windows_json)
        if schedule is not None
        else [dict(item) for item in DEFAULT_ANALYSIS_WINDOWS]
    )
    schedule_closed = bool(
        schedule
        and schedule.enabled
        and not is_within_windows(now, windows)
    )
    waiting = (
        analysis.status in {"pending", "running"}
        and job.status == "pending"
        and job.immediate_requested_at is None
        and schedule_closed
    )
    return AnalysisQueueState(
        stage=job.stage,
        execution_mode=(
            "immediate" if job.immediate_requested_at is not None else "scheduled"
        ),
        waiting_for_schedule=waiting,
        next_eligible_at=next_window_start(now, windows) if waiting else None,
    )


def _get_or_create_profile(session: Session) -> UserProfileRecord:
    """读取单用户画像；首次访问时创建默认评测配置。"""

    profile = session.get(UserProfileRecord, "default")
    if profile is None:
        profile = UserProfileRecord(id="default")
        session.add(profile)
        session.commit()
    return profile


def _get_or_create_user_state(session: Session) -> CurrentUserStateRecord:
    """读取当前阅读状态；首次访问时创建空状态。"""

    record = session.get(CurrentUserStateRecord, "default")
    if record is None:
        record = CurrentUserStateRecord(id="default")
        session.add(record)
        session.commit()
    return record


def _user_state_response(record: CurrentUserStateRecord) -> CurrentUserStateResponse:
    """将状态持久化字段转换为稳定 API 契约。"""

    return CurrentUserStateResponse(
        active_goals=list(record.active_goals_json),
        active_questions=list(record.active_questions_json),
        focus_context=record.focus_context,
        available_minutes=record.available_minutes,
        preferred_depth=record.preferred_depth,
        exploration_level=record.exploration_level,
        valid_until=record.valid_until,
        updated_at=record.updated_at,
    )


def _profile_response(profile: UserProfileRecord) -> ProfileResponse:
    """将画像持久化字段转换为稳定 API 契约。"""

    return ProfileResponse(
        focus_topics=profile.focus_topics_json,
        known_topics=profile.known_topics_json,
        reading_goals=profile.reading_goals_json,
        preferred_depth=profile.preferred_depth,
        time_budget_minutes=profile.time_budget_minutes,
        exploration_level=profile.exploration_level,
        evaluation_mode=profile.evaluation_mode,
        questionnaire_completed=profile.questionnaire_completed_at is not None,
        updated_at=profile.updated_at,
    )


def _analysis_snapshot(analysis: Analysis) -> dict:
    """冻结反馈提交时用于比较的三阶段 AI 输出。"""

    return {
        "triage": analysis.triage_json,
        "content_analysis": analysis.content_analysis_json,
        "personal_evaluation": analysis.personal_evaluation_json,
    }


def _feedback_response(feedback: ArticleFeedback) -> FeedbackResponse:
    """构造不暴露完整 AI 快照的详情页反馈响应。"""

    return FeedbackResponse(
        id=feedback.id,
        analysis_id=feedback.analysis_id,
        preferred_recommendation=feedback.preferred_recommendation,
        recommendation_accuracy=feedback.recommendation_accuracy,
        time_worthwhile=feedback.time_worthwhile,
        new_knowledge=feedback.new_knowledge,
        summary_quality=feedback.summary_quality,
        key_takeaway=feedback.key_takeaway,
        ai_recommendation=feedback.ai_recommendation,
        model=feedback.model,
        prompt_version=feedback.prompt_version,
        updated_at=feedback.updated_at,
    )


def _memory_revision_response(revision: CognitiveMemoryRevision) -> MemoryRevisionResponse:
    """把不可变版本转换为稳定 API 契约。"""

    return MemoryRevisionResponse(
        id=revision.id,
        cognitive_memory_id=revision.cognitive_memory_id,
        version=revision.version,
        statement=revision.statement,
        awareness_state=revision.awareness_state,
        stance=revision.stance,
        lifecycle=revision.lifecycle,
        confidence=revision.confidence,
        topics=list(revision.topics_json),
        entities=list(revision.entities_json),
        source_type=revision.source_type,
        created_at=revision.created_at,
        confirmed_at=revision.confirmed_at,
    )


def _memory_summary(session: Session, memory: CognitiveMemory) -> MemorySummaryResponse:
    """读取 Memory 当前版本并构造列表级响应。"""

    revision = session.get(CognitiveMemoryRevision, memory.current_revision_id) if memory.current_revision_id else None
    revision_count = int(
        session.scalar(
            select(func.count())
            .select_from(CognitiveMemoryRevision)
            .where(CognitiveMemoryRevision.cognitive_memory_id == memory.id)
        )
        or 0
    )
    return MemorySummaryResponse(
        id=memory.id,
        current_revision=_memory_revision_response(revision) if revision else None,
        created_at=memory.created_at,
        revision_count=revision_count,
    )


def _proposal_response(proposal: MemoryChangeProposal) -> MemoryProposalResponse:
    """把内部 Proposal 记录转换为稳定 API 契约。"""

    return MemoryProposalResponse(
        id=proposal.id,
        action=proposal.action,
        target_memory_id=proposal.target_memory_id,
        expected_current_revision_id=proposal.expected_current_revision_id,
        candidate_memory_revision_ids=list(proposal.candidate_memory_revision_ids_json),
        proposed_statement=proposal.proposed_statement,
        proposed_awareness_state=proposal.proposed_awareness_state,
        proposed_stance=proposal.proposed_stance,
        proposed_lifecycle=proposal.proposed_lifecycle,
        evidence_claim_ids=list(proposal.evidence_claim_ids_json),
        reason=proposal.reason,
        status=proposal.status,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
    )


def _memory_write_response(
    session: Session,
    outcome: str,
    memory_id: str | None,
    proposal_id: str | None,
    match,
) -> MemoryWriteResponse:
    """按匹配结果构造写入响应；proposal 场景不返回 Memory。"""

    memory = _memory_summary(session, session.get(CognitiveMemory, memory_id)) if memory_id else None
    return MemoryWriteResponse(
        outcome=outcome,
        memory=memory,
        proposal_id=proposal_id,
        match_source=match.match_source,
        reason=match.reason,
    )


def _claim_response_rows(rows: list[ContentClaim]) -> list[ContentClaimContract]:
    """把行级 ORM Claims 转换为详情页契约对象。"""

    return [
        ContentClaimContract(
            claim_id=item.claim_id,
            claim=item.statement,
            claim_type=item.claim_type,
            claim_role=item.claim_role,
            change_signal=item.change_signal,
            section_ref=item.section_ref,
            evidence=list(item.evidence_json),
            verification=item.verification,
            topics=list(item.topics_json),
            entities=list(item.entities_json),
        )
        for item in rows
    ]


def _cognitive_delta(session: Session, analysis: Analysis) -> CognitiveDeltaResponse | None:
    """读取 Compare 结果；未完成、失败或旧分析返回 None。"""

    if not analysis.cognitive_compare_run_id:
        return None
    run = session.get(CognitiveCompareRun, analysis.cognitive_compare_run_id)
    if run is None or run.status != "completed" or not run.compare_output_json:
        return None
    relations = run.compare_output_json.get("relations", [])
    corrections = session.scalars(
        select(ClaimCorrection)
        .where(
            ClaimCorrection.analysis_id == analysis.id,
            ClaimCorrection.correction_type == "primary_relation",
        )
        .order_by(ClaimCorrection.created_at)
    ).all()
    # 纠错引用行级 Claim 主键，relations 使用分析内 claim_id，需要映射。
    claim_ids_by_row = {
        item.id: item.claim_id
        for item in session.scalars(
            select(ContentClaim).where(ContentClaim.analysis_id == analysis.id)
        )
    }
    return CognitiveDeltaResponse(
        retrieval_context=run.retrieval_context_json,
        relations=relations,
        effective_relations=_effective_relations(relations, corrections, claim_ids_by_row),
        claim_corrections=[_claim_correction_response(item) for item in corrections],
        derived_summary=run.derived_summary_json or {},
    )


def _effective_relations(
    relations: list[dict],
    corrections: list[ClaimCorrection],
    claim_ids_by_row: dict[str, str],
) -> list[dict]:
    """把最新 primary_relation 纠错应用到展示值；原始 relations 不变。"""

    latest_by_claim: dict[str, ClaimCorrection] = {}
    for correction in corrections:
        claim_id = claim_ids_by_row.get(correction.content_claim_id)
        if claim_id is not None:
            latest_by_claim[claim_id] = correction
    effective = []
    for relation in relations:
        claim_id = relation.get("current_claim_id")
        correction = latest_by_claim.get(claim_id)
        if correction is None or not claim_id:
            effective.append(relation)
            continue
        item = dict(relation)
        item["primary_relation"] = correction.corrected_value
        item["original_primary_relation"] = relation.get("primary_relation")
        effective.append(item)
    return effective


def _claim_correction_response(correction: ClaimCorrection) -> ClaimCorrectionResponse:
    """把纠错记录转换为稳定 API 契约。"""

    return ClaimCorrectionResponse(
        id=correction.id,
        analysis_id=correction.analysis_id,
        content_claim_id=correction.content_claim_id,
        correction_type=correction.correction_type,
        original_value=correction.original_value,
        corrected_value=correction.corrected_value,
        matched_memory_revision_ids=list(correction.matched_memory_revision_ids_json),
        evidence_status=correction.evidence_status,
        reason=correction.reason,
        created_at=correction.created_at,
    )


def _load_analysis_claim(
    session: Session, analysis_id: str, claim_id: str
) -> ContentClaim:
    """校验 Claim 属于指定分析并返回行级记录。"""

    claim = session.scalar(
        select(ContentClaim).where(
            ContentClaim.analysis_id == analysis_id,
            ContentClaim.claim_id == claim_id,
        )
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="该分析中不存在此 Claim")
    return claim


def _correction_original_value(
    claim: ContentClaim,
    run: CognitiveCompareRun | None,
    correction_type: str,
) -> str:
    """读取纠错对象的原始值：关系来自 Compare，角色来自行级 Claim。"""

    if correction_type == "claim_role":
        return claim.claim_role
    if run is not None and run.compare_output_json:
        for relation in run.compare_output_json.get("relations", []):
            if relation.get("current_claim_id") == claim.claim_id:
                return relation.get("primary_relation", "new")
    return "new"


def _compare_run_response(session: Session, run: CognitiveCompareRun) -> CompareRunResponse:
    """把 CompareRun 转换为诊断接口契约。"""

    delta = _cognitive_delta(session, session.get(Analysis, run.analysis_id))
    return CompareRunResponse(
        id=run.id,
        analysis_id=run.analysis_id,
        status=run.status,
        current_claim_ids=list(run.current_claim_ids_json),
        current_memory_candidate_revision_ids=list(
            run.current_memory_candidate_revision_ids_json
        ),
        historical_memory_candidate_revision_ids=list(
            run.historical_memory_candidate_revision_ids_json
        ),
        retrieval_context=run.retrieval_context_json,
        delta=delta,
        model=run.model,
        prompt_version=run.prompt_version,
        last_error=run.last_error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _unauthorized_response() -> JSONResponse:
    """构造 Web 与插件都能统一识别的未登录响应。"""

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "未登录或登录已过期"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def run() -> None:
    """以开发配置启动 API 服务。"""

    uvicorn.run("signallens.main:app", host="127.0.0.1", port=8000, reload=False)
