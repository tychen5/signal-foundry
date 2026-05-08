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

import contextvars
import os
from typing import Optional

from langchain_core.language_models import BaseChatModel

from src.config import LLMProvider, Settings, get_settings

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Per-request user API key overrides — set by the routers via
# `set_user_keys()` before invoking the agent/pipeline. get_llm consults
# this when the explicit `user_*_key` arguments are absent. Uses
# contextvars so concurrent requests don't trample each other.
_user_openrouter_key_ctx: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "user_openrouter_key_ctx", default=None
)
_user_nvidia_key_ctx: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "user_nvidia_key_ctx", default=None
)


def set_user_keys(openrouter: Optional[str] = None, nvidia: Optional[str] = None) -> None:
    """Set per-request user API keys.

    Routers call this at the start of a request so that downstream get_llm()
    callers (which only know about a single `user_openrouter_key` parameter)
    can transparently use the user-supplied NVIDIA NIM key too. Keys are
    isolated per asyncio task via contextvars — concurrent requests don't
    leak keys across each other.
    """
    if openrouter is not None:
        _user_openrouter_key_ctx.set(openrouter)
    if nvidia is not None:
        _user_nvidia_key_ctx.set(nvidia)


def clear_user_keys() -> None:
    """Reset the per-request key context (call at request teardown)."""
    _user_openrouter_key_ctx.set(None)
    _user_nvidia_key_ctx.set(None)


def get_llm(
    model_name: Optional[str] = None,
    user_openrouter_key: Optional[str] = None,
    user_nvidia_key: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    settings: Optional[Settings] = None,
    json_mode: bool = False,
) -> BaseChatModel:
    """
    Create a LangChain chat model instance for the given model name.

    Args:
        model_name: Model identifier (e.g., "openai/gpt-5.5"). Uses default if None.
        user_openrouter_key: User-supplied OpenRouter key (overrides server key).
        user_nvidia_key: User-supplied NVIDIA NIM key (overrides server key).
            Useful when the server's key is expired or rate-limited.
        temperature: Sampling temperature. Default 0.0 for deterministic output.
        max_tokens: Max tokens for response. Uses model default if None.
        settings: Settings instance. Uses singleton if None.
        json_mode: When True, request response_format={"type":"json_object"}.
            All major OpenAI-compat backends (OpenRouter, NVIDIA NIM ≥2024-12)
            support this and it removes a whole class of "could not parse JSON"
            errors. Silently ignored by older backends.

    Returns:
        BaseChatModel instance ready for .invoke() / .ainvoke() / .stream()

    Raises:
        ValueError: If model_name is not in the registry, or no API key
            is available for the selected provider.
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
        api_key = (
            user_openrouter_key
            or _user_openrouter_key_ctx.get()
            or settings.openrouter_api_key
        )
        if not api_key:
            raise ValueError(
                "OpenRouter API key required for this model. Either set "
                "OPENROUTER_API_KEY on the server, or paste your own key in "
                "the UI's 'OpenRouter API Key' field. Get one at openrouter.ai."
            )
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
            json_mode=json_mode,
        )

    if provider == LLMProvider.NVIDIA:
        api_key = (
            user_nvidia_key
            or _user_nvidia_key_ctx.get()
            or settings.nvidia_api_key
        )
        if not api_key:
            raise ValueError(
                "NVIDIA NIM API key required. Either set NVIDIA_API_KEY on "
                "the server, or paste your own key (`nvapi-...`) in the UI's "
                "'NVIDIA NIM API Key' field. Free keys: build.nvidia.com."
            )
        if backend == "langchain_native":
            return _create_nvidia_native(actual_model, api_key, temperature, max_tokens, extra_body)
        return _create_openai_compat(
            model_name=actual_model,
            api_key=api_key,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            provider_label="nvidia",
            json_mode=json_mode,
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
    json_mode: bool = False,
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
        # Cap individual LLM calls. Gemini 3.1 Pro thinking-mode can take 60+s
        # for hard reasoning tasks; we set a 90s ceiling so an upstream hang
        # surfaces as a timeout error instead of stalling SSE streams. Browser
        # agent runs benefit from a tighter timeout because they make many
        # short calls; T3 stage-2 boundary refinement uses snippets so 90s
        # is more than enough.
        "timeout": float(os.environ.get("LLM_REQUEST_TIMEOUT_S", "90")),
    }
    # `extra_body` is accepted by ChatOpenAI in all versions ≥0.2.10 (our
    # minimum). Earlier versions silently ate it; newer versions emit a
    # UserWarning if we pass it via model_kwargs. The simplest correct path
    # is to pass it as a top-level kwarg — ChatOpenAI's __init__ uses
    # **kwargs and forwards to the openai SDK which accepts extra_body.
    if extra_body:
        chat_kwargs["extra_body"] = extra_body

    # JSON mode (response_format) eliminates a whole class of "could not
    # parse" errors when the prompt expects strict JSON output. Compatibility:
    #   ✓ kimi-k2.6, minimax-m2.7 (NVIDIA, plain models)
    #   ✓ gpt-5.5, claude-opus-4.7, gemini-3.1-pro-preview (OpenRouter)
    #   ✗ glm-5.1, deepseek-v4-pro (thinking-mode — extra_body conflicts with
    #     response_format=json_object on NIM; the model returns
    #     reasoning_content+content as separate blocks and json_object
    #     forces a single string. Disabled to avoid silent empty responses.)
    # The robust extract_json_object helper is the fallback for both cases.
    if json_mode and not extra_body:
        chat_kwargs["model_kwargs"] = chat_kwargs.get("model_kwargs", {}) or {}
        chat_kwargs["model_kwargs"]["response_format"] = {"type": "json_object"}

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
