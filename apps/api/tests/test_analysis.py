"""三阶段分析契约与 Provider 的单元测试。"""

import json

import httpx
import pytest

from signallens.analysis.provider import AnalysisProviderError, OpenAICompatibleProvider
from signallens.analysis.schemas import AnalyzeContent, EvaluateForUser, TriageContent


def test_triage_rejects_ignoring_high_signal_content() -> None:
    """低相关但有内容信号的文章不能被快速分诊直接忽略。"""

    with pytest.raises(ValueError, match="只有内容信号和探索价值都低时才允许忽略"):
        TriageContent(
            relevance="low",
            intrinsic_signal="high",
            novelty_signal="high",
            exploration_value="high",
            discovery_type="adjacent",
            decision="ignore",
            reason="与当前关注主题不一致",
            why_outside_profile=None,
        )


def test_evaluation_protects_high_exploration_value() -> None:
    """高探索价值不能因画像相关性低而得到忽略建议。"""

    with pytest.raises(ValueError, match="高探索价值内容不能建议忽略"):
        EvaluateForUser(
            relevance="low",
            knowledge_overlap="low",
            known_or_redundant=False,
            novel_information=["新领域方法"],
            exploration_value="high",
            perspective_diversity="high",
            discovery_type="outside_profile_high_value",
            recommendation="ignore",
            recommendation_reason="相关性低",
            why_outside_profile="提供跨领域视角",
            reading_plan=[],
        )


def test_openai_compatible_provider_validates_structured_output() -> None:
    """Provider 应发送 JSON Schema，并把模型 JSON 校验成 Pydantic 对象。"""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["response_format"]["json_schema"]["name"] == "TriageContent"
        result = {
            "relevance": "medium",
            "intrinsic_signal": "high",
            "novelty_signal": "unknown",
            "exploration_value": "medium",
            "discovery_type": "adjacent",
            "decision": "continue",
            "reason": "文章信号充分，值得继续分析",
            "why_outside_profile": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(result)}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    provider = OpenAICompatibleProvider(
        base_url="https://llm.example/v1/",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    result = provider.complete(
        system_prompt="system",
        user_prompt="user",
        output_model=TriageContent,
    )
    assert result.decision == "continue"


def test_output_schema_meets_strict_json_schema_requirements() -> None:
    """严格输出中的每个对象都必须禁止额外字段且声明全部属性为必填。"""

    for output_model in (TriageContent, AnalyzeContent, EvaluateForUser):
        schema = output_model.model_json_schema()
        objects = [schema, *schema.get("$defs", {}).values()]
        for value in objects:
            if value.get("type") != "object":
                continue
            assert value["additionalProperties"] is False
            assert set(value["required"]) == set(value["properties"])


def test_openai_compatible_provider_rejects_invalid_json() -> None:
    """不符合契约的模型输出必须转成统一 Provider 错误。"""

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )
    )
    provider = OpenAICompatibleProvider(
        base_url="https://llm.example/v1",
        api_key="test-key",
        model="test-model",
        client=httpx.Client(transport=transport),
    )
    with pytest.raises(AnalysisProviderError, match="模型未返回有效的 TriageContent"):
        provider.complete(
            system_prompt="system",
            user_prompt="user",
            output_model=TriageContent,
        )
