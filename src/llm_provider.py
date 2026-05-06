"""
Unified LLM Provider Factory for Signal-Foundry.

Both NVIDIA NIM and OpenRouter are OpenAI-compatible. Rather than juggle
two provider-specific wrappers (langchain-nvidia-ai-endpoints and
langchain-openrouter), each with their own quirks (NIM's "Multiple
candidates" assertions, OpenRouter wrapper version drift), the default
backend is `langchain_openai.ChatOpenAI` pointed at the right `base_url`.
This is mature, battle-tested, and gives us a single code path for both.

Provider-specific wrappers remain as opt-in fallbacks via
`LLM_BACKEND=langchain_native` for users who want their full feature set.

Users can supply their own OpenRouter API key per-request to avoid consuming
the server owner's token budget.
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel

from src.config import LLMProvider, Settings, get_settings

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_llm(
    model_name: Optional[str] = None,
    user_openrouter_key: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> BaseChatModel:
    """
    Create a LangChain chat model instance for the given model name.

    Args:
        model_name: Model identifier (e.g., "openai/gpt-5.5"). Uses default if None.
        user_openrouter_key: User-supplied OpenRouter key (overrides server key).
        temperature: Sampling temperature. Default 0.0 for deterministic output.
        max_tokens: Max tokens for response. Uses model default if None.
        settings: Settings instance. Uses singleton if None.

    Returns:
        BaseChatModel instance ready for .invoke() / .ainvoke() / .stream()

    Raises:
        ValueError: If model_name is not in the registry.
        ImportError: If required provider package is not installed.
    """
    if settings is None:
        settings = get_settings()

    if model_name is None:
        model_name = settings.default_model

    model_info = settings.get_model_info(model_name)
    provider = model_info["provider"]
    actual_model = model_info["model_name"]
    default_max_tokens = model_info.get("max_tokens", 8192)
    extra_body = model_info.get("extra_body")

    if max_tokens is None:
        max_tokens = default_max_tokens

    backend = os.environ.get("LLM_BACKEND", "openai_compat").lower()

    if provider == LLMProvider.OPENROUTER:
        api_key = user_openrouter_key or settings.openrouter_api_key
        if backend == "langchain_native":
            return _create_openrouter_native(actual_model, api_key, temperature, max_tokens)
        return _create_openai_compat(
            model_name=actual_model,
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            provider_label="openrouter",
        )

    if provider == LLMProvider.NVIDIA:
        if not settings.nvidia_api_key:
            raise ValueError("NVIDIA API key required. Set NVIDIA_API_KEY env var.")
        if backend == "langchain_native":
            return _create_nvidia_native(actual_model, settings.nvidia_api_key, temperature, max_tokens, extra_body)
        return _create_openai_compat(
            model_name=actual_model,
            api_key=settings.nvidia_api_key,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            provider_label="nvidia",
        )

    raise ValueError(f"Unsupported provider: {provider}")


def _create_openai_compat(
    model_name: str,
    api_key: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
    extra_body: Optional[dict] = None,
    provider_label: str = "openai",
) -> BaseChatModel:
    """Universal OpenAI-compatible chat model.

    Works for any provider that exposes an OpenAI-style /v1/chat/completions
    endpoint — NVIDIA NIM, OpenRouter, vLLM, LM Studio, etc. `extra_body`
    carries provider-specific request body extensions (e.g. NIM's
    `chat_template_kwargs.thinking` toggle).

    For OpenRouter we also send the `HTTP-Referer` / `X-OpenRouter-Title`
    headers — OpenRouter uses them for app attribution and rankings (and
    occasionally for routing decisions). They're optional but cheap.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "langchain-openai package not installed. "
            "Run: pip install langchain-openai"
        ) from e

    if not api_key:
        raise ValueError(f"{provider_label.upper()} API key required.")

    default_headers: dict = {}
    if provider_label == "openrouter":
        default_headers = {
            "HTTP-Referer": "https://signal-foundry.zeabur.app",
            "X-OpenRouter-Title": "Signal-Foundry",
        }

    # `extra_body` placement varies across langchain-openai versions:
    # - newer (≥0.3): top-level kwarg
    # - older: must be nested inside `model_kwargs` (and the wrapper warns).
    # We probe at runtime so we don't pin a specific dependency version.
    import inspect as _inspect
    accepts_extra_body_top = "extra_body" in _inspect.signature(ChatOpenAI.__init__).parameters

    chat_kwargs: dict = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "default_headers": default_headers or None,
        # NIM and OpenRouter occasionally rate-limit or hiccup; surface the
        # error to the caller fast rather than silently retrying inside the SDK.
        "max_retries": 1,
    }
    if extra_body:
        if accepts_extra_body_top:
            chat_kwargs["extra_body"] = extra_body
        else:
            chat_kwargs["model_kwargs"] = {"extra_body": extra_body}

    return ChatOpenAI(**chat_kwargs)


def _create_openrouter_native(
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> BaseChatModel:
    """Optional: use the dedicated langchain-openrouter wrapper."""
    try:
        from langchain_openrouter import ChatOpenRouter
    except ImportError as e:
        raise ImportError(
            "langchain-openrouter package not installed. "
            "Run: pip install langchain-openrouter (or unset LLM_BACKEND)"
        ) from e

    if not api_key:
        raise ValueError("OpenRouter API key required.")

    return ChatOpenRouter(
        model=model_name,
        openrouter_api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_nvidia_native(
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    extra_body: Optional[dict],
) -> BaseChatModel:
    """Optional: use the dedicated langchain-nvidia-ai-endpoints wrapper.

    Has occasional quirks ("Multiple candidates" assertions on dual-listed
    models, type-unknown warnings on hosted-only models) — kept available
    for users who want NVIDIA-specific features like NIM's accelerated
    streaming.
    """
    try:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
    except ImportError as e:
        raise ImportError(
            "langchain-nvidia-ai-endpoints package not installed. "
            "Run: pip install langchain-nvidia-ai-endpoints (or unset LLM_BACKEND)"
        ) from e

    kwargs: dict = {
        "model": model_name,
        "api_key": api_key,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    return ChatNVIDIA(**kwargs)


def list_available_models() -> list[dict]:
    """List all available models with their display names and providers."""
    return Settings.list_models()
