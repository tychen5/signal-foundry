"""
Configuration module for Signal-Foundry.

Manages environment variables, model registry, and application settings.
Supports dual LLM providers: OpenRouter and NVIDIA AI Endpoints.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMProvider(str, Enum):
    """Supported LLM provider backends."""

    OPENROUTER = "openrouter"
    NVIDIA = "nvidia"


# --- Model Registry ---
# Maps model identifiers to their provider and actual model name
MODEL_REGISTRY: dict[str, dict] = {
    # OpenRouter models
    "openai/gpt-5.5": {
        "provider": LLMProvider.OPENROUTER,
        "model_name": "openai/gpt-5.5",
        "display_name": "GPT-5.5 (OpenAI)",
        "max_tokens": 16384,
    },
    "anthropic/claude-opus-4.7": {
        "provider": LLMProvider.OPENROUTER,
        "model_name": "anthropic/claude-opus-4.7",
        "display_name": "Claude Opus 4.7 (Anthropic)",
        "max_tokens": 16384,
    },
    "google/gemini-3.1-pro-preview": {
        "provider": LLMProvider.OPENROUTER,
        "model_name": "google/gemini-3.1-pro-preview",
        "display_name": "Gemini 3.1 Pro (Google)",
        "max_tokens": 16384,
    },
    # NVIDIA AI Endpoints models
    "moonshotai/kimi-k2.6": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "moonshotai/kimi-k2.6",
        "display_name": "Kimi K2.6 (Moonshot)",
        "max_tokens": 8192,
    },
    "z-ai/glm-5.1": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "z-ai/glm-5.1",
        "display_name": "GLM 5.1 (Zhipu AI)",
        "max_tokens": 8192,
    },
    "deepseek-ai/deepseek-v4-pro": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "deepseek-ai/deepseek-v4-pro",
        "display_name": "DeepSeek V4 Pro",
        "max_tokens": 16384,
    },
    "minimaxai/minimax-m2.7": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "minimaxai/minimax-m2.7",
        "display_name": "MiniMax M2.7",
        "max_tokens": 8192,
    },
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Providers
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    nvidia_api_key: str = Field(default="", description="NVIDIA AI Endpoints API key")
    default_model: str = Field(default="moonshotai/kimi-k2.6", description="Default LLM model")

    # GitHub (Task 1)
    github_token: str = Field(default="", description="GitHub Personal Access Token")

    # LangSmith (observability)
    langsmith_api_key: str = Field(default="", description="LangSmith API key")
    langsmith_project: str = Field(default="signal-foundry", description="LangSmith project name")
    langsmith_tracing: bool = Field(default=True, description="Enable LangSmith tracing")

    # SEC EDGAR (Task 3)
    sec_user_agent: str = Field(
        default="signal-foundry/1.0 (signal-foundry@example.com)",
        description="User-Agent header for SEC API requests",
    )
    sec_cache_dir: str = Field(
        default="/tmp/signal_foundry_sec_cache",
        description="Disk cache directory for SEC filings and metadata",
    )
    sec_max_download_mb: int = Field(
        default=200,
        description="Maximum SEC filing download size in megabytes",
    )
    sec_request_timeout_sec: float = Field(
        default=120.0,
        description="Timeout for SEC API and filing download requests",
    )

    # Application
    app_host: str = Field(default="0.0.0.0", description="Application host")
    app_port: int = Field(default=8080, description="Application port")
    log_level: str = Field(default="INFO", description="Logging level")
    environment: str = Field(default="development", description="Environment name")

    # Cost Discipline
    max_cost_per_request_usd: float = Field(default=2.0, description="Max USD cost per request")
    max_tokens_per_request: int = Field(default=100000, description="Max tokens per request")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}

    def get_model_info(self, model_id: str) -> dict:
        """Get model configuration by ID. Falls back to default model if not found."""
        if model_id in MODEL_REGISTRY:
            return MODEL_REGISTRY[model_id]
        return MODEL_REGISTRY.get(self.default_model, list(MODEL_REGISTRY.values())[0])

    @staticmethod
    def list_models() -> list[dict]:
        """List all available models with their display names and providers."""
        return [
            {
                "id": model_id,
                "display_name": info["display_name"],
                "provider": info["provider"].value,
            }
            for model_id, info in MODEL_REGISTRY.items()
        ]


# Singleton settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the singleton Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
