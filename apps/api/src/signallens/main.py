"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import create_schema, get_session
from .models import Analysis, AnalysisJob, Content
from .schemas import (
    AnalysisResponse,
    CaptureAccepted,
    CaptureRequest,
    ContentDetailResponse,
    ContentSummaryResponse,
    HealthResponse,
)
from .settings import get_settings
from .urls import normalize_content_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时准备开发数据库结构。"""

    create_schema()
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


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """返回无需鉴权的存活状态。"""

    return HealthResponse(status="ok", service="signallens-api")


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
    summary = _content_summary(content, analysis)
    return ContentDetailResponse(
        **summary.model_dump(),
        markdown=content.markdown,
        triage=analysis.triage_json,
        content_analysis=analysis.content_analysis_json,
        personal_evaluation=analysis.personal_evaluation_json,
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


def run() -> None:
    """以开发配置启动 API 服务。"""

    uvicorn.run("signallens.main:app", host="127.0.0.1", port=8000, reload=False)
