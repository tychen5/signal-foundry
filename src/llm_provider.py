"""
Unified LLM Provider Factory for Signal-Foundry.

Supports dual backends:
- OpenRouter (langchain-openrouter): GPT-5.5, Claude Opus 4.7, Gemini 3.1 Pro
- NVIDIA AI Endpoints (langchain-nvidia-ai-endpoints): Kimi K2.6, GLM 5.1, DeepSeek V4 Pro, MiniMax M2.7

Users can supply their own OpenRouter API key per-request to avoid consuming
the server owner's token budget.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel

from src.config import LLMProvider, Settings, get_settings


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
        BaseChatModel instance ready for .invoke() / .stream()

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

    if max_tokens is None:
        max_tokens = default_max_tokens

    if provider == LLMProvider.OPENROUTER:
        return _create_openrouter_model(
            model_name=actual_model,
            api_key=user_openrouter_key or settings.openrouter_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif provider == LLMProvider.NVIDIA:
        return _create_nvidia_model(
            model_name=actual_model,
            api_key=settings.nvidia_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _create_openrouter_model(
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> BaseChatModel:
    """Create an OpenRouter-backed chat model."""
    try:
        from langchain_openrouter import ChatOpenRouter
    except ImportError:
        raise ImportError(
            "langchain-openrouter package not installed. "
            "Run: pip install langchain-openrouter"
        )

    if not api_key:
        raise ValueError(
            "OpenRouter API key required. Set OPENROUTER_API_KEY env var "
            "or provide user_openrouter_key parameter."
        )

    return ChatOpenRouter(
        model=model_name,
        openrouter_api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_nvidia_model(
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> BaseChatModel:
    """Create an NVIDIA AI Endpoints-backed chat model."""
    try:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
    except ImportError:
        raise ImportError(
            "langchain-nvidia-ai-endpoints package not installed. "
            "Run: pip install langchain-nvidia-ai-endpoints"
        )

    if not api_key:
        raise ValueError(
            "NVIDIA API key required. Set NVIDIA_API_KEY env var."
        )

    return ChatNVIDIA(
        model=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def list_available_models() -> list[dict]:
    """List all available models with their display names and providers."""
    return Settings.list_models()
