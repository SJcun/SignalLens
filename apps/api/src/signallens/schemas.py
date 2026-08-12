"""API 输入、输出和未来 AI 结构化结果的数据契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


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
    triage: dict | None
    content_analysis: dict | None
    personal_evaluation: dict | None
    created_at: datetime
    completed_at: datetime | None


class HealthResponse(BaseModel):
    """部署探针使用的健康状态。"""

    status: Literal["ok"]
    service: Literal["signallens-api"]

