"""版本化三阶段 Prompt；修改行为时必须同步提升版本。"""

import json
from typing import Any

from pydantic import BaseModel

from .schemas import AnalyzeContent, TriageContent, UserProfile

PROMPT_VERSION = "v0.3.0"

TRIAGE_SYSTEM_PROMPT = """你是 SignalLens 的快速阅读分诊器。
只根据给定内容和简要关注主题判断是否值得继续分析，不产生最终阅读建议。
低相关不等于低价值；必须分别判断内容信号、新颖性和探索价值。
手动采集代表明确用户意图，除非内容明显无效，否则 decision 必须为 continue。
只有低信号、高重复或低质量且没有探索价值的组合才允许 ignore。
不确定时选择 continue。严格按给定 JSON Schema 输出。"""

ANALYZE_SYSTEM_PROMPT = """你是 SignalLens 的内容分析器。
只分析文章本身，不使用或猜测用户画像。摘要必须忠于原文，不得制造反方观点。
如果原文存在反对意见、限制、不确定性或未验证主张，必须保留在对应字段中。
章节名称尽量沿用原文，以便用户定位阅读。严格按给定 JSON Schema 输出。"""

EVALUATE_SYSTEM_PROMPT = """你是 SignalLens 的个性化阅读评估器。
结合内容分析和明确提供的用户画像生成阅读建议。
区分主题熟悉度与文章价值；低相关但高探索价值的内容仍可选择性阅读或精读。
不得把用户未声明的知识或偏好当作事实。画像为空时应保守判断知识重叠。
严格按给定 JSON Schema 输出。"""


def triage_input(content: dict[str, Any], profile: UserProfile) -> str:
    """构造快速分诊输入，只暴露简要关注主题。"""

    return _json_text({"content": content, "focus_topics": profile.focus_topics})


def analyze_input(content: dict[str, Any], triage: TriageContent) -> str:
    """构造内容分析输入，不传递用户画像。"""

    return _json_text({"content": content, "triage": triage.model_dump()})


def evaluate_input(analysis: AnalyzeContent, profile: UserProfile) -> str:
    """构造个性化评估输入，显式传入分析结果和最小画像。"""

    return _json_text(
        {"content_analysis": analysis.model_dump(), "user_profile": profile.model_dump()}
    )


def _json_text(value: dict[str, Any] | BaseModel) -> str:
    """以稳定的 Unicode JSON 传递结构化上下文。"""

    payload = value.model_dump() if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
