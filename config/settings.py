"""
Configuration Management for CVHR AI Agent
Sử dụng pydantic-settings để load và validate config từ environment.

Kiến trúc giống etax_kekhaithue: các sub-settings class gom nhóm cấu hình,
Settings tổng hợp lại, get_settings() dùng lru_cache singleton.
Được tối ưu chuẩn Pydantic V2 để loại bỏ tất cả warnings.
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache


class LLMSettings(BaseSettings):
    """Cấu hình LLM (Gemini)."""
    google_api_key: str = Field(..., validation_alias="GOOGLE_API_KEY")
    model: str = Field(default="gemini-2.5-flash", validation_alias="LLM_MODEL")
    temperature: float = Field(default=0.1, validation_alias="LLM_TEMPERATURE")
    max_tokens: int = Field(default=8192, validation_alias="LLM_MAX_TOKENS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class APISettings(BaseSettings):
    """Cấu hình API Server (FastAPI)."""
    host: str = Field(default="127.0.0.1", validation_alias="API_HOST")
    port: int = Field(default=8000, validation_alias="API_PORT")
    debug: bool = Field(default=False, validation_alias="API_DEBUG")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class SessionSettings(BaseSettings):
    """Cấu hình Session & Memory."""
    ttl_hours: int = Field(default=24, validation_alias="SESSION_TTL_HOURS")
    max_conversation_turns: int = Field(default=50, validation_alias="MAX_CONVERSATION_TURNS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class LangfuseSettings(BaseSettings):
    """Cấu hình Langfuse tracing.

    Langfuse dùng 3 biến:
    - LANGFUSE_SECRET_KEY
    - LANGFUSE_PUBLIC_KEY
    - LANGFUSE_HOST

    Nếu secret_key hoặc public_key rỗng → Langfuse disabled (không trace).
    """
    secret_key: Optional[str] = Field(default=None, validation_alias="LANGFUSE_SECRET_KEY")
    public_key: Optional[str] = Field(default=None, validation_alias="LANGFUSE_PUBLIC_KEY")
    base_url: Optional[str] = Field(default=None, validation_alias="LANGFUSE_HOST")

    @property
    def enabled(self) -> bool:
        """True khi cả secret_key và public_key đều có giá trị."""
        return bool(self.secret_key and self.public_key)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class LangSmithSettings(BaseSettings):
    """Cấu hình LangSmith tracing.

    LangSmith dùng env vars chuẩn:
    - LANGCHAIN_TRACING_V2=true
    - LANGCHAIN_API_KEY=...
    - LANGCHAIN_PROJECT=cvhr-agent
    """
    tracing_enabled: bool = Field(default=False, validation_alias="LANGCHAIN_TRACING_V2")
    api_key: Optional[str] = Field(default=None, validation_alias="LANGCHAIN_API_KEY")
    project: str = Field(default="cvhr-agent", validation_alias="LANGCHAIN_PROJECT")

    @property
    def enabled(self) -> bool:
        return self.tracing_enabled and bool(self.api_key)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class Settings(BaseSettings):
    """Master Settings — tổng hợp tất cả sub-configurations.

    Sử dụng:
        from config.settings import get_settings
        settings = get_settings()
        print(settings.llm.model)  # "gemini-2.5-flash"
    """

    # Sub-configurations
    llm: LLMSettings = Field(default_factory=LLMSettings)
    api: APISettings = Field(default_factory=APISettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    langsmith: LangSmithSettings = Field(default_factory=LangSmithSettings)

    # Logging
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: str = Field(default="json", validation_alias="LOG_FORMAT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Singleton pattern để cache settings.

    Sử dụng:
        settings = get_settings()
        print(settings.llm.google_api_key)
    """
    return Settings()
