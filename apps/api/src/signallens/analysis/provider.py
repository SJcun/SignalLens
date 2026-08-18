"""OpenAI-compatible 结构化输出 Provider。"""

import json
from typing import TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class AnalysisProviderError(RuntimeError):
    """模型请求失败或返回不符合分析契约时抛出的统一异常。"""


class OpenAICompatibleProvider:
    """调用兼容 OpenAI Chat Completions 的结构化输出接口。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        response_format_mode: str = "auto",
        max_tokens: int = 16384,
        client: httpx.Client | None = None,
    ) -> None:
        """保存连接配置；测试可注入 MockTransport 驱动的客户端。"""

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.response_format_mode = response_format_mode
        self.max_tokens = max_tokens
        self.client = client or httpx.Client(timeout=120)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        """按服务能力请求 JSON，并在进入业务层前完成 Pydantic 校验。"""

        schema = output_model.model_json_schema()
        mode = self._resolved_response_format_mode()
        previous_error: AnalysisProviderError | None = None

        for attempt in range(2):
            request_prompt = self._build_system_prompt(
                system_prompt=system_prompt,
                schema=schema,
                mode=mode,
                previous_error=previous_error,
            )
            response = self._post_completion(
                system_prompt=request_prompt,
                user_prompt=user_prompt,
                output_model=output_model,
                schema=schema,
                mode=mode,
            )

            try:
                choice = response.json()["choices"][0]
                content = choice["message"]["content"]
                finish_reason = choice.get("finish_reason")
                if not isinstance(content, str) or not content.strip():
                    raise TypeError("message.content 为空或不是字符串")
                if finish_reason == "length":
                    raise AnalysisProviderError(
                        f"{output_model.__name__} 输出被截断：finish_reason=length，"
                        f"max_tokens={self.max_tokens}，已接收 {len(content)} 个字符"
                    )
                return output_model.model_validate_json(content)
            except AnalysisProviderError as exc:
                previous_error = exc
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                previous_error = AnalysisProviderError(
                    f"模型未返回有效的 {output_model.__name__}: {exc}"
                )

            # DeepSeek 的 JSON Output 偶尔会截断或产生不合约输出；自动以精简指令
            # 重试一次。严格 json_schema 仅在明确达到长度上限时重试。
            should_retry = attempt == 0 and (
                mode == "json_object" or "finish_reason=length" in str(previous_error)
            )
            if not should_retry:
                raise previous_error

        raise previous_error or AnalysisProviderError(f"{output_model.__name__} 分析失败")

    def _post_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
        schema: dict,
        mode: str,
    ) -> httpx.Response:
        """发送一次模型请求，并保留非成功响应的服务端错误正文。"""

        if mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            response_format = {"type": "json_object"}

        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": response_format,
        }
        if self._is_deepseek():
            # DeepSeek V4 默认思考模式会与最终 JSON 共享输出预算；结构化抽取
            # 使用非思考模式更稳定，也避免推理内容挤占 JSON 的结束部分。
            payload["thinking"] = {"type": "disabled"}

        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            # 保留服务端返回的参数错误正文，避免日志中只剩一个无法诊断的 400。
            detail = exc.response.text.strip()[:2000] or exc.response.reason_phrase
            raise AnalysisProviderError(
                f"模型请求失败（HTTP {exc.response.status_code}）：{detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AnalysisProviderError(f"模型请求失败：{exc}") from exc

    def _build_system_prompt(
        self,
        *,
        system_prompt: str,
        schema: dict,
        mode: str,
        previous_error: AnalysisProviderError | None,
    ) -> str:
        """为 JSON Output 注入契约，并为第二次请求增加精简纠错指令。"""

        result = system_prompt
        if mode == "json_object":
            # DeepSeek 的 JSON Output 只保证合法 JSON，因此把完整契约交给模型，
            # 返回后仍由 Pydantic 执行业务约束和字段校验。
            result += (
                "\n\n你必须只输出一个符合下列 JSON Schema 的 JSON 对象，"
                "不要输出 Markdown 代码块或额外说明：\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
        if previous_error is not None:
            result += (
                "\n\n上一次 JSON 输出被截断或未通过契约校验。请显著缩短所有摘要和列表，"
                "确保完整输出右花括号。不要解释错误。"
            )
        return result

    def _resolved_response_format_mode(self) -> str:
        """自动识别 DeepSeek，其他服务默认使用严格 JSON Schema。"""

        if self.response_format_mode in {"json_schema", "json_object"}:
            return self.response_format_mode
        if self.response_format_mode != "auto":
            raise ValueError(f"不支持的响应格式模式：{self.response_format_mode}")

        if self._is_deepseek():
            return "json_object"
        return "json_schema"

    def _is_deepseek(self) -> bool:
        """判断当前地址是否为 DeepSeek 官方 API。"""

        hostname = urlparse(self.base_url).hostname or ""
        return hostname == "deepseek.com" or hostname.endswith(".deepseek.com")


def build_provider_from_settings() -> OpenAICompatibleProvider | None:
    """按运行配置构造 Provider；未配置 LLM 时返回 None。"""

    from ..settings import get_settings

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_model:
        return None
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        response_format_mode=settings.llm_response_format,
        max_tokens=settings.llm_max_tokens,
    )
