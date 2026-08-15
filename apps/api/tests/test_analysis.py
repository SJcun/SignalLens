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
        assert body["max_tokens"] == 16384
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


def test_deepseek_uses_json_object_with_schema_in_prompt() -> None:
    """DeepSeek 自动降级为 JSON Output，并在 Prompt 中携带完整契约。"""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/chat/completions"
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert '"required"' in body["messages"][0]["content"]
        result = {
            "relevance": "medium",
            "intrinsic_signal": "high",
            "novelty_signal": "unknown",
            "exploration_value": "medium",
            "discovery_type": "adjacent",
            "decision": "continue",
            "reason": "值得继续分析",
            "why_outside_profile": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(result)}}]},
        )

    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    result = provider.complete(
        system_prompt="输出 JSON",
        user_prompt="user",
        output_model=TriageContent,
    )
    assert result.decision == "continue"


def test_deepseek_retries_truncated_json_with_compact_instruction() -> None:
    """DeepSeek 达到输出上限时应自动精简重试一次。"""

    request_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        body = json.loads(request.content)
        if request_count == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": '{"reason":"被截断'},
                        }
                    ]
                },
            )

        assert "上一次 JSON 输出被截断" in body["messages"][0]["content"]
        result = {
            "relevance": "medium",
            "intrinsic_signal": "high",
            "novelty_signal": "unknown",
            "exploration_value": "medium",
            "discovery_type": "adjacent",
            "decision": "continue",
            "reason": "精简后的有效结果",
            "why_outside_profile": None,
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(result)}}
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    result = provider.complete(
        system_prompt="输出 JSON",
        user_prompt="user",
        output_model=TriageContent,
    )
    assert request_count == 2
    assert result.reason == "精简后的有效结果"


def test_output_schema_meets_strict_json_schema_requirements() -> None:
    """严格输出中的每个对象都必须禁止额外字段且必填字段齐全。"""

    for output_model in (TriageContent, AnalyzeContent, EvaluateForUser):
        schema = output_model.model_json_schema()
        objects = [schema, *schema.get("$defs", {}).values()]
        for value in objects:
            if value.get("type") != "object":
                continue
            assert value["additionalProperties"] is False
            assert set(value["required"]) <= set(value["properties"])

    analyze_schema = AnalyzeContent.model_json_schema()
    assert analyze_schema["properties"]["summary"]["maxLength"] == 1600
    assert analyze_schema["properties"]["content_map"]["maxItems"] == 10
    # 模型输出契约保留 section_ref 引用字段，历史读取时允许为空。
    section_def = analyze_schema["$defs"]["ContentSection"]
    assert "section_ref" in section_def["properties"]

    evaluate_schema = EvaluateForUser.model_json_schema()
    assert evaluate_schema["properties"]["reading_plan"]["maxItems"] == 10


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


def test_provider_preserves_http_error_body() -> None:
    """HTTP 参数错误应包含服务端正文，便于直接定位不兼容字段。"""

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            400,
            json={"error": {"message": "response_format.type is invalid"}},
        )
    )
    provider = OpenAICompatibleProvider(
        base_url="https://llm.example/v1",
        api_key="test-key",
        model="test-model",
        client=httpx.Client(transport=transport),
    )
    with pytest.raises(AnalysisProviderError, match="response_format.type is invalid"):
        provider.complete(
            system_prompt="system",
            user_prompt="user",
            output_model=TriageContent,
        )
