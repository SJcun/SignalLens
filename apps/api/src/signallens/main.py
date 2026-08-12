"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import (
    create_session,
    ensure_initial_admin,
    hash_password,
    load_session,
    remove_bootstrap_password_file,
    revoke_user_sessions,
    verify_password,
)
from .database import SessionLocal, create_schema, get_session
from .models import (
    AdminUser,
    Analysis,
    AnalysisJob,
    ArticleFeedback,
    AuthSession,
    Content,
    UserProfileRecord,
    utc_now,
)
from .schemas import (
    AnalysisResponse,
    CalibrationStatsResponse,
    CaptureAccepted,
    CaptureRequest,
    ChangePasswordRequest,
    ContentDetailResponse,
    ContentSummaryResponse,
    CurrentUserResponse,
    FeedbackResponse,
    FeedbackUpsert,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    ProfileResponse,
    ProfileUpdate,
)
from .settings import get_settings
from .urls import normalize_content_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时准备数据库结构和唯一初始管理员。"""

    create_schema()
    ensure_initial_admin()
    yield


settings = get_settings()
app = FastAPI(title="SignalLens API", version="0.1.0", lifespan=lifespan)
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
        authenticated = load_session(session, raw_token)
        if authenticated is None:
            return _unauthorized_response()
        user, auth_session = authenticated
        # 请求只携带后续端点需要的稳定标识，不跨数据库会话传递 ORM 对象。
        request.state.auth_user_id = user.id
        request.state.auth_username = user.username
        request.state.must_change_password = user.must_change_password
        request.state.auth_session_id = auth_session.id
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
    """修改管理员密码，并撤销 Web 与插件的全部旧会话。"""

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
        return _accepted(existing, analysis)

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
    return _accepted(content, analysis)


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisResponse:
    """返回分析状态和已完成的结构化结果。"""

    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return _analysis_response(analysis)


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
    # 防止新 Prompt 与旧阶段结果混用。
    analysis.status = "pending"
    analysis.triage_json = None
    analysis.content_analysis_json = None
    analysis.personal_evaluation_json = None
    analysis.model = None
    analysis.prompt_version = "unimplemented"
    analysis.completed_at = None
    job.stage = "triage"
    job.status = "pending"
    job.last_error = None
    session.commit()
    return _accepted(content, analysis)


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

    evaluation = analysis.personal_evaluation_json or {}
    feedback = session.scalar(
        select(ArticleFeedback).where(ArticleFeedback.analysis_id == analysis.id)
    )
    if feedback is None:
        feedback = ArticleFeedback(
            content_id=analysis.content_id,
            analysis_id=analysis.id,
            recommendation_accuracy=payload.recommendation_accuracy,
            time_worthwhile=payload.time_worthwhile,
            new_knowledge=payload.new_knowledge,
            summary_quality=payload.summary_quality,
            key_takeaway=payload.key_takeaway,
            # 分诊阶段直接忽略时不会生成个人评估，也要保留 AI 的原始建议，
            # 否则无法统计用户认为值得阅读的漏判。
            ai_recommendation=evaluation.get("recommendation")
            or (
                "ignore"
                if (analysis.triage_json or {}).get("decision") == "ignore"
                else None
            ),
            model=analysis.model,
            prompt_version=analysis.prompt_version,
            analysis_snapshot_json=_analysis_snapshot(analysis),
        )
        session.add(feedback)
    else:
        # 更新人工评价，但保留首次提交时冻结的 AI 快照和版本。
        feedback.recommendation_accuracy = payload.recommendation_accuracy
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
    accurate = sum(item.recommendation_accuracy == "accurate" for item in feedbacks)
    too_high = sum(item.recommendation_accuracy == "too_high" for item in feedbacks)
    too_low = sum(item.recommendation_accuracy == "too_low" for item in feedbacks)
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
    )


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
        select(Content, Analysis)
        .join(Analysis, Analysis.id == latest_analysis_id)
        .order_by(Content.created_at.desc())
        .limit(safe_limit)
    ).all()
    return [_content_summary(content, analysis) for content, analysis in rows]


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
    summary = _content_summary(content, analysis)
    return ContentDetailResponse(
        **summary.model_dump(),
        markdown=content.markdown,
        triage=analysis.triage_json,
        content_analysis=analysis.content_analysis_json,
        personal_evaluation=analysis.personal_evaluation_json,
        feedback=_feedback_response(feedback) if feedback else None,
    )


def _content_summary(content: Content, analysis: Analysis) -> ContentSummaryResponse:
    """从持久化 JSON 中安全提取 Inbox 所需的少量展示字段。"""

    content_analysis = analysis.content_analysis_json or {}
    personal_evaluation = analysis.personal_evaluation_json or {}
    triage = analysis.triage_json or {}
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
        recommendation=personal_evaluation.get("recommendation") or (
            "ignore" if triage.get("decision") == "ignore" else None
        ),
        discovery_type=personal_evaluation.get("discovery_type") or triage.get("discovery_type"),
    )


def _accepted(content: Content, analysis: Analysis) -> CaptureAccepted:
    """统一构造异步采集响应。"""

    return CaptureAccepted(
        content_id=content.id,
        analysis_id=analysis.id,
        status=analysis.status,
        detail_url=f"/contents/{content.id}",
    )


def _analysis_response(analysis: Analysis) -> AnalysisResponse:
    """统一构造分析状态响应并触发结构化结果校验。"""

    return AnalysisResponse(
        id=analysis.id,
        content_id=analysis.content_id,
        status=analysis.status,
        triage=analysis.triage_json,
        content_analysis=analysis.content_analysis_json,
        personal_evaluation=analysis.personal_evaluation_json,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


def _get_or_create_profile(session: Session) -> UserProfileRecord:
    """读取单用户画像；首次访问时创建默认评测配置。"""

    profile = session.get(UserProfileRecord, "default")
    if profile is None:
        profile = UserProfileRecord(id="default")
        session.add(profile)
        session.commit()
    return profile


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
