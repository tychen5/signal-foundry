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
# Maps model identifiers to their provider and actual model name.
#
# `extra_body` is forwarded to ChatNVIDIA on construction. NVIDIA NIM exposes
# some "thinking" models (DeepSeek V4 Pro, Kimi K2 Thinking) where reasoning
# content is wrapped separately from the answer. Setting
# {"chat_template_kwargs": {"thinking": False}} switches them into a plain
# chat-completion mode that returns just the answer text — which is what every
# downstream task in this repo expects.
MODEL_REGISTRY: dict[str, dict] = {
    # ==================================================================
    # NVIDIA NIM (free tier — DEFAULT for reviewers without their own key)
    # ==================================================================
    # kimi-k2.6 is first because it's the recommended default: free,
    # fast (no thinking-mode latency tax), reliable structured output.
    "moonshotai/kimi-k2.6": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "moonshotai/kimi-k2.6",
        "display_name": "Kimi K2.6 (NVIDIA, free) — DEFAULT",
        "max_tokens": 16384,
    },
    "z-ai/glm-5.1": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "z-ai/glm-5.1",
        "display_name": "GLM 5.1 (NVIDIA, free, thinking)",
        "max_tokens": 16384,
        # GLM 5.1 thinking-mode toggles use different keys than DeepSeek.
        # `enable_thinking=True` keeps reasoning available;
        # `clear_thinking=False` keeps the answer text in `content` so we
        # don't have to reassemble it from `reasoning_content`.
        "extra_body": {
            "chat_template_kwargs": {
                "enable_thinking": True,
                "clear_thinking": False,
            }
        },
    },
    "deepseek-ai/deepseek-v4-pro": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "deepseek-ai/deepseek-v4-pro",
        "display_name": "DeepSeek V4 Pro (NVIDIA, free, thinking)",
        "max_tokens": 16384,
        # Default thinking=True: empirically gives noticeably better answers on
        # the structured-extraction prompts in this repo (skill matching,
        # 10-K boundary refinement, browser action planning), at the cost of
        # extra reasoning tokens (200+ s per call). Final answer still lands
        # in .content; reasoning_content is captured separately and ignored
        # downstream. Use this for hard tasks where latency is acceptable.
        "extra_body": {"chat_template_kwargs": {"thinking": True}},
    },
    "minimaxai/minimax-m2.7": {
        "provider": LLMProvider.NVIDIA,
        "model_name": "minimaxai/minimax-m2.7",
        "display_name": "MiniMax M2.7 (NVIDIA, free)",
        "max_tokens": 8192,
    },
    # ==================================================================
    # OpenRouter (paid tier — reviewers should supply their own key)
    # ==================================================================
    # Gemini 3.1 Pro Preview is first because it's the recommended paid
    # fallback: cheap ($0.00125/1K in, $0.005/1K out), high-quality, fast.
    "google/gemini-3.1-pro-preview": {
        "provider": LLMProvider.OPENROUTER,
        "model_name": "google/gemini-3.1-pro-preview",
        "display_name": "Gemini 3.1 Pro (OpenRouter, paid)",
        "max_tokens": 16384,
    },
    "anthropic/claude-opus-4.7": {
        "provider": LLMProvider.OPENROUTER,
        "model_name": "anthropic/claude-opus-4.7",
        "display_name": "Claude Opus 4.7 (OpenRouter, paid, premium)",
        "max_tokens": 16384,
    },
    "openai/gpt-5.5": {
        "provider": LLMProvider.OPENROUTER,
        "model_name": "openai/gpt-5.5",
        "display_name": "GPT-5.5 (OpenRouter, paid)",
        "max_tokens": 16384,
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

    # Zeabur deployment metadata (optional, surfaced in /health for ops visibility)
    zeabur_domain: str = Field(default="", description="Public Zeabur domain")
    zeabur_server_ip: str = Field(default="", description="Zeabur dedicated server IP")
    zeabur_api_key: str = Field(default="", description="Zeabur control-plane API key")
    zeabur_cluster_api_key: str = Field(default="", description="Zeabur cluster API key")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    def get_model_info(
        self,
        model_id: str,
        provider_hint: Optional[str] = None,
    ) -> dict:
        """Get model configuration for a (possibly free-text) model_id.

        Resolution order:
          1. Exact MODEL_REGISTRY hit → use the registered config
             (preserves curated `extra_body` for thinking-mode models +
             documented `max_tokens` + display_name).
          2. `provider_hint` is "openrouter" or "nvidia" → synthesise a
             pass-through config for that provider.
          3. Prefix heuristic via `infer_provider_from_model_id` → same.
          4. Nothing fits → raise ValueError so the caller can return 400
             with a clear "set provider explicitly" message instead of
             silently swapping in the demo default model (which has bitten
             reviewers running benchmarks with their own model IDs).

        This lets users bring ANY model the chosen provider hosts — e.g.
        `qwen/qwen3-next-80b-a3b-instruct`, `nvidia/nemotron-3-super-...`,
        or anything new on openrouter.ai — without us needing to ship a
        registry update.
        """
        from src.shared.llm_validation import (
            infer_provider_from_model_id,
            validate_model_id_shape,
        )

        shape_error = validate_model_id_shape(model_id)
        if shape_error:
            raise ValueError(shape_error)

        if model_id in MODEL_REGISTRY:
            return MODEL_REGISTRY[model_id]

        # Free-text path: synthesise a config from the hint or heuristic.
        provider_str: Optional[str] = None
        hint = provider_hint.strip().lower() if provider_hint else None
        if hint in ("openrouter", "nvidia"):
            provider_str = hint
        elif hint:
            raise ValueError(f"provider hint must be 'openrouter' or 'nvidia', got {provider_hint!r}.")
        else:
            provider_str = infer_provider_from_model_id(model_id)

        if not provider_str:
            raise ValueError(
                f"Cannot infer provider for free-text model_id {model_id!r}. "
                "Set `model.provider` to 'openrouter' or 'nvidia' explicitly, "
                "or pick a model whose publisher prefix is recognised "
                "(openai/, anthropic/, google/, moonshotai/, qwen/, nvidia/, …)."
            )

        return {
            "provider": LLMProvider(provider_str),
            "model_name": model_id,
            "display_name": f"{model_id} (free-text, {provider_str})",
            # Conservative cap. Users running long-context workflows
            # (Task 3 SEC filings) should explicitly pick a registry
            # model that ships a higher cap; this default keeps free-text
            # runs reasonably bounded.
            "max_tokens": 8192,
            "extra_body": None,
        }

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
