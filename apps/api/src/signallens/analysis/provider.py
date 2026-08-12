"""OpenAI-compatible 结构化输出 Provider。"""

from typing import TypeVar

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
        client: httpx.Client | None = None,
    ) -> None:
        """保存连接配置；测试可注入 MockTransport 驱动的客户端。"""

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=120)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        """请求严格 JSON Schema 输出并在进入业务层前完成校验。"""

        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": output_model.__name__,
                            "strict": True,
                            "schema": output_model.model_json_schema(),
                        },
                    },
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content 不是字符串")
            return output_model.model_validate_json(content)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise AnalysisProviderError(f"模型未返回有效的 {output_model.__name__}: {exc}") from exc
