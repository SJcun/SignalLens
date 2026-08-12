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
        max_tokens: int = 8192,
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
            # DeepSeek 的 JSON Output 只保证合法 JSON，因此把完整契约交给模型，
            # 返回后仍由 Pydantic 执行业务约束和字段校验。
            system_prompt = (
                f"{system_prompt}\n\n你必须只输出一个符合下列 JSON Schema 的 JSON 对象，"
                "不要输出 Markdown 代码块或额外说明：\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )

        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "max_tokens": self.max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": response_format,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # 保留服务端返回的参数错误正文，避免日志中只剩一个无法诊断的 400。
            detail = exc.response.text.strip()[:2000] or exc.response.reason_phrase
            raise AnalysisProviderError(
                f"模型请求失败（HTTP {exc.response.status_code}）：{detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AnalysisProviderError(f"模型请求失败：{exc}") from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content 不是字符串")
            return output_model.model_validate_json(content)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise AnalysisProviderError(f"模型未返回有效的 {output_model.__name__}: {exc}") from exc

    def _resolved_response_format_mode(self) -> str:
        """自动识别 DeepSeek，其他服务默认使用严格 JSON Schema。"""

        if self.response_format_mode in {"json_schema", "json_object"}:
            return self.response_format_mode
        if self.response_format_mode != "auto":
            raise ValueError(f"不支持的响应格式模式：{self.response_format_mode}")

        hostname = urlparse(self.base_url).hostname or ""
        if hostname == "deepseek.com" or hostname.endswith(".deepseek.com"):
            return "json_object"
        return "json_schema"
