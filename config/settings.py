"""Validated application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


def _runtime_path(local_path: str, vercel_path: str) -> Path:
    """Use Vercel's writable temporary directory when running serverless."""
    return Path(vercel_path if os.getenv("VERCEL") else local_path)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str = "gpt-4o"
    max_output_tokens: int = Field(default=350, ge=64, le=4000)
    model_input_price_per_million: float = Field(default=2.50, ge=0)
    model_output_price_per_million: float = Field(default=10.00, ge=0)
    max_input_chars: int = Field(default=2000, ge=100, le=20_000)
    max_uploaded_log_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    max_context_messages: int = Field(default=6, ge=2, le=50)
    max_agent_steps: int = Field(default=4, ge=2, le=20)
    rate_limit_requests: int = Field(default=20, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    memory_db_path: Path = Field(
        default_factory=lambda: _runtime_path("data/agent_memory.db", "/tmp/agent_memory.db")
    )
    audit_log_path: Path = Field(
        default_factory=lambda: _runtime_path("data/audit.jsonl", "/tmp/audit.jsonl")
    )
    usage_admin_key: str | None = Field(default=None, repr=False)
    operator_api_key: str | None = Field(default=None, repr=False)
    auth_mode: Literal["api_key", "oidc_proxy"] = "api_key"
    oidc_proxy_secret: str | None = Field(default=None, repr=False)
    approval_signing_secret: str | None = Field(default=None, repr=False)
    session_retention_days: int = Field(default=30, ge=1, le=365)
    tool_mode: Literal["mock", "live"] = "mock"
    monitoring_api_url: str | None = None
    orchestration_api_url: str | None = None
    tool_api_token: str | None = Field(default=None, repr=False)
    tool_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    allowed_services: str = "auth-service,payment-gateway"
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=256, ge=64, le=3072)
    semantic_memory_threshold: float = Field(default=0.96, ge=0.5, le=1.0)
    image_generation_enabled: bool = True
    image_model: str = "gpt-image-2"
    image_size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1536x1024"
    image_quality: Literal["low", "medium", "high"] = "medium"
    generated_image_dir: Path = Field(
        default_factory=lambda: _runtime_path("web/generated", "/tmp/generated")
    )
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = Field(default=None, repr=False)
    langchain_project: str = "OpsSentinel-AI"

    @property
    def service_allowlist(self) -> set[str]:
        return {item.strip() for item in self.allowed_services.split(",") if item.strip()}

    @field_validator(
        "usage_admin_key", "operator_api_key", "approval_signing_secret",
        "oidc_proxy_secret", "tool_api_token", mode="before"
    )
    @classmethod
    def normalize_optional_secret(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_production(self):
        if self.usage_admin_key and len(self.usage_admin_key) < 16:
            raise ValueError("USAGE_ADMIN_KEY must contain at least 16 characters")
        if self.operator_api_key and len(self.operator_api_key) < 16:
            raise ValueError("OPERATOR_API_KEY must contain at least 16 characters")
        if self.approval_signing_secret and len(self.approval_signing_secret) < 32:
            raise ValueError("APPROVAL_SIGNING_SECRET must contain at least 32 characters")
        if self.oidc_proxy_secret and len(self.oidc_proxy_secret) < 24:
            raise ValueError("OIDC_PROXY_SECRET must contain at least 24 characters")
        if self.app_env == "production" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required in production")
        if self.app_env == "production" and self.tool_mode == "mock":
            raise ValueError("TOOL_MODE=mock is forbidden in production")
        if self.app_env == "production" and not self.usage_admin_key:
            raise ValueError("USAGE_ADMIN_KEY is required in production")
        if self.app_env == "production" and self.auth_mode == "api_key" and not self.operator_api_key:
            raise ValueError("OPERATOR_API_KEY is required for production api_key authentication")
        if self.app_env == "production" and self.auth_mode == "oidc_proxy" and not self.oidc_proxy_secret:
            raise ValueError("OIDC_PROXY_SECRET is required for production oidc_proxy authentication")
        if self.app_env == "production" and not self.approval_signing_secret:
            raise ValueError("APPROVAL_SIGNING_SECRET is required in production")
        if self.app_env == "production" and (
            not self.monitoring_api_url or not self.orchestration_api_url or not self.tool_api_token
        ):
            raise ValueError(
                "MONITORING_API_URL, ORCHESTRATION_API_URL, and TOOL_API_TOKEN are required in production"
            )
        if self.embedding_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
