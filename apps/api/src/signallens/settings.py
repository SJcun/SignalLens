"""应用配置：集中读取环境变量，避免业务代码直接依赖进程环境。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SignalLens 运行配置。"""

    env: str = "development"
    database_url: str = "sqlite:///./data/signallens.db"
    web_origin: str = "http://localhost:5173"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_response_format: str = "auto"
    llm_max_tokens: int = 8192

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SIGNALLENS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """返回进程内复用的配置实例。"""

    return Settings()
