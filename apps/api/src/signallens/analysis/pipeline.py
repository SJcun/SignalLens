"""三阶段分析调用边界，不在此处理数据库任务状态。"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .compare import CognitiveCompare
from .prompts import (
    ANALYZE_SYSTEM_PROMPT,
    COMPARE_SYSTEM_PROMPT,
    EVALUATE_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    analyze_input,
    compare_input,
    evaluate_input,
    triage_input,
)
from .schemas import AnalyzeContent, CurrentUserState, EvaluateForUser, TriageContent, UserProfile
from .sections import SectionIndex

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class StructuredOutputProvider(Protocol):
    """分析流水线依赖的最小结构化输出能力。"""

    model: str

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        """返回经过 Pydantic 契约校验的模型输出。"""


@dataclass(frozen=True)
class AnalysisInput:
    """从持久化内容快照中提取出的模型输入。"""

    title: str
    source_url: str
    source_type: str
    capture_mode: str
    capture_quality: str
    markdown: str
    # 模型调用前由系统解析出的主章节清单；没有合适层级时为 None。
    section_index: SectionIndex | None = None

    def as_prompt_data(self) -> dict[str, str | dict | None]:
        """转换为三个阶段共用的稳定字典结构。"""

        return {
            "title": self.title,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "capture_mode": self.capture_mode,
            "capture_quality": self.capture_quality,
            "markdown": self.markdown,
            "section_index": (
                self.section_index.model_dump(mode="json") if self.section_index else None
            ),
        }


def run_triage(
    provider: StructuredOutputProvider,
    content: AnalysisInput,
    profile: UserProfile,
) -> TriageContent:
    """执行快速分诊，并强制保护用户主动提交的有效内容。"""

    result = provider.complete(
        system_prompt=TRIAGE_SYSTEM_PROMPT,
        user_prompt=triage_input(content.as_prompt_data(), profile),
        output_model=TriageContent,
    )
    if content.capture_mode == "manual" and content.capture_quality != "failed":
        return result.model_copy(update={"decision": "continue"})
    return result


def run_content_analysis(
    provider: StructuredOutputProvider,
    content: AnalysisInput,
    triage: TriageContent,
) -> AnalyzeContent:
    """执行不依赖用户画像的内容本体分析。"""

    return provider.complete(
        system_prompt=ANALYZE_SYSTEM_PROMPT,
        user_prompt=analyze_input(content.as_prompt_data(), triage),
        output_model=AnalyzeContent,
    )


def run_personal_evaluation(
    provider: StructuredOutputProvider,
    analysis: AnalyzeContent,
    profile: UserProfile,
    user_state: CurrentUserState | None = None,
    delta_summary: dict | None = None,
) -> EvaluateForUser:
    """结合最小画像、当前阅读状态与代码生成的认知差异执行最终评估。

    delta_summary 为空（Memory 为空、召回失败或 Compare 失败）时，
    Evaluate 回退到保守逻辑，不得声称用户已知具体内容。
    """

    return provider.complete(
        system_prompt=EVALUATE_SYSTEM_PROMPT,
        user_prompt=evaluate_input(
            analysis,
            profile,
            user_state or CurrentUserState(),
            delta_summary,
        ),
        output_model=EvaluateForUser,
    )


def run_cognitive_compare(
    provider: StructuredOutputProvider,
    *,
    claims: list[dict],
    current_candidates: list[dict],
    historical_candidates: list[dict],
    retrieval_context: dict,
) -> CognitiveCompare:
    """执行逐 Claim 认知比较；结构校验由调用方完成。"""

    return provider.complete(
        system_prompt=COMPARE_SYSTEM_PROMPT,
        user_prompt=compare_input(
            claims,
            current_candidates,
            historical_candidates,
            retrieval_context,
        ),
        output_model=CognitiveCompare,
    )
