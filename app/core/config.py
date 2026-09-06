"""Application settings (pydantic-settings)."""

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="QUE-Agent", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    cors_allow_origins: str = Field(default="", alias="CORS_ALLOW_ORIGINS")

    que_service_key: str = Field(default="", alias="QUE_SERVICE_KEY")
    allow_insecure_local_no_auth: bool = Field(default=False, alias="ALLOW_INSECURE_LOCAL_NO_AUTH")

    # Shared with Quizzer Backend — used to verify browser Que access JWTs.
    # Separate from QUE_SERVICE_KEY (server-to-server only).
    que_jwt_secret: str = Field(default="", alias="QUE_JWT_SECRET")
    que_jwt_algorithm: str = Field(default="HS256", alias="QUE_JWT_ALGORITHM")
    que_jwt_audience: str = Field(default="que-agent", alias="QUE_JWT_AUDIENCE")
    que_jwt_issuer: str = Field(default="quizzer", alias="QUE_JWT_ISSUER")

    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="openai/gpt-4o-mini", alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=45.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_tokens: int = Field(default=700, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.35, alias="LLM_TEMPERATURE")

    # QUE-owned in-process cache (NOT Quizzer Redis).
    que_cache_enabled: bool = Field(default=True, alias="QUE_CACHE_ENABLED")
    que_cache_max_entries: int = Field(default=512, alias="QUE_CACHE_MAX_ENTRIES")
    que_cache_intent_ttl_seconds: float = Field(default=3600.0, alias="QUE_CACHE_INTENT_TTL_SECONDS")
    que_cache_llm_ttl_seconds: float = Field(default=900.0, alias="QUE_CACHE_LLM_TTL_SECONDS")
    que_cache_variant_ttl_seconds: float = Field(default=1800.0, alias="QUE_CACHE_VARIANT_TTL_SECONDS")

    # Short-term conversation memory (LangGraph MemorySaver, per worker).
    que_memory_enabled: bool = Field(default=True, alias="QUE_MEMORY_ENABLED")
    que_memory_max_turns: int = Field(default=20, alias="QUE_MEMORY_MAX_TURNS")

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8100, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_local(self) -> bool:
        return self.app_env.lower() in {"local", "dev", "development"}

    @property
    def cors_origins(self) -> list[str]:
        if not self.cors_allow_origins.strip():
            return []
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @field_validator("que_jwt_secret", "que_service_key")
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def enforce_production_guards(self) -> "Settings":
        if not self.is_local:
            if self.allow_insecure_local_no_auth:
                raise ValueError("ALLOW_INSECURE_LOCAL_NO_AUTH cannot be true outside local/dev")
            weak = {
                "change-me-to-a-long-random-secret",
                "changeme",
                "secret",
                "",
            }
            if not self.que_jwt_secret or self.que_jwt_secret in weak or len(self.que_jwt_secret) < 32:
                raise ValueError(
                    "QUE_JWT_SECRET must be a strong secret (≥32 chars) in non-local environments"
                )
            # Service key remains required for future QUE→Quizzer tool calls / ops.
            if not self.que_service_key or self.que_service_key in weak:
                raise ValueError("QUE_SERVICE_KEY must be set to a strong secret in non-local environments")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
