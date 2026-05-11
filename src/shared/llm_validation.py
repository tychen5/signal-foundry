"""
LLM input validation for user-facing APIs.

Every Task 1/2/3 endpoint that calls an LLM goes through these helpers
*before* burning network/LLM cycles. The goal is to fail fast with a
specific, actionable error rather than letting the request slog all the
way to the provider and bounce back with a generic "Internal error: ..."
that the user can't act on.

Three checks per request:

1. **model_id shape** — must be non-empty and contain a slash
   (`provider/model-name`). This is the convention OpenRouter, NVIDIA NIM,
   HuggingFace TGI, and most OpenAI-compatible gateways use, so the slash
   is a cheap structural guard against typos like `gpt-5.5` (missing
   `openai/`).

2. **provider resolution** — for free-text model_ids the user might
   bring (e.g. `qwen/qwen3-next-80b-a3b-instruct`, `nvidia/nemotron-3-…`)
   we infer the provider from the prefix when an explicit hint isn't
   set. Falls back to the request's `provider` field, then to the model
   registry, then to a prefix heuristic, then errors out cleanly.

3. **key presence** — once we know the provider, we verify a key is
   actually available (user-supplied or server-fallback). If not, return
   400 with a message naming exactly which key field to populate.

If any of these fail, the router can return a structured 400 with
`{stage: "input_validation", category: "..."}` so the FE can render the
right inline error without any LLM round-trip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Provider prefix heuristics for free-text model_ids that aren't in the
# server-side MODEL_REGISTRY. These mirror how the actual providers
# namespace their models — `openai/...` and `anthropic/...` are routed
# through OpenRouter; the NIM catalog uses the *publisher's* own prefix
# (`moonshotai/...`, `meta/...`, `nvidia/...` etc.).
#
# NOT exhaustive — we don't try to catalogue every model on both
# providers; we cover the common publishers the user mentioned plus the
# ones the existing demo registry uses. Unknown prefixes return `None`
# and force the user to set `provider` explicitly.
_NVIDIA_PUBLISHER_PREFIXES = (
    "nvidia/",
    "moonshotai/",
    "z-ai/",
    "deepseek-ai/",
    "minimaxai/",
    "meta/",
    "qwen/",
    "tencent/",
    "01-ai/",
    "ibm/",
    "writer/",
    "snowflake/",
    "databricks/",
    "microsoft/",
    "mistralai/mistral-small-3",  # NIM-hosted Mistral variants
)

_OPENROUTER_PUBLISHER_PREFIXES = (
    "openai/",
    "anthropic/",
    "google/",
    "x-ai/",
    "cohere/",
    "mistralai/",  # OpenRouter mostly — overlap with NIM caught above
    "deepseek/",
    "perplexity/",
    "fireworks/",
    "together/",
)


@dataclass
class ModelResolution:
    """Outcome of resolving (model_id, provider, key) for a request."""

    valid: bool
    model_id: str
    provider: Optional[str]  # "openrouter" | "nvidia" | None
    error_category: Optional[str]  # "missing_model_id" | "bad_model_id_shape" | "ambiguous_provider" | "missing_key"
    error_message: Optional[str]
    error_field: Optional[str]  # which JSON field the user should fix


def validation_error_to_envelope(
    resolution: ModelResolution,
    *,
    stage: str = "input_validation",
) -> dict:
    """Convert a failed model/key resolution into a user-facing API envelope."""
    return {
        "stage": stage,
        "provider": resolution.provider,
        "model_id": resolution.model_id,
        "status_code": None,
        "status_label": None,
        "category": resolution.error_category or "invalid_input",
        "user_message": resolution.error_message or "Invalid LLM configuration.",
        "suggested_action": (
            f"Fix `{resolution.error_field}` and retry." if resolution.error_field else "Fix the model block and retry."
        ),
        "raw_error": resolution.error_message or "",
        "retryable": False,
        "error_field": resolution.error_field,
    }


def validate_model_selection(
    model: object,
    *,
    require_key: bool = True,
) -> ModelResolution:
    """Validate the Pydantic `model` block used by public task APIs.

    Kept model-typed as `object` to avoid importing shared schemas here and
    creating a circular import. The routers pass `ModelSelectionRequest`.
    """
    from src.config import MODEL_REGISTRY, get_settings

    settings = get_settings()
    return resolve_model_and_keys(
        model_id=getattr(model, "model_id", None),
        provider_hint=getattr(model, "provider", None),
        user_openrouter_key=getattr(model, "user_openrouter_key", None),
        user_nvidia_key=getattr(model, "user_nvidia_key", None),
        server_openrouter_key=settings.openrouter_api_key if require_key else "not-required",
        server_nvidia_key=settings.nvidia_api_key if require_key else "not-required",
        known_models=MODEL_REGISTRY,
    )


def validate_model_id_shape(model_id: Optional[str]) -> Optional[str]:
    """Return an error message if the model_id shape is bad, else None."""
    if model_id is None:
        return "model_id is required."
    s = model_id.strip()
    if not s:
        return "model_id cannot be empty or whitespace-only."
    if "/" not in s:
        return (
            f"model_id must be in 'provider/model-name' format "
            f"(e.g. 'openai/gpt-5.5', 'anthropic/claude-opus-4.7', "
            f"'moonshotai/kimi-k2.6', 'qwen/qwen3-next-80b-a3b-instruct'). "
            f"Got: {model_id!r}."
        )
    parts = s.split("/", 1)
    if not parts[0].strip() or not parts[1].strip():
        return f"model_id has an empty publisher or model name on one side of '/': {model_id!r}."
    # Block obvious junk that would make routing nonsense
    if re.search(r"\s", s):
        return f"model_id must not contain whitespace: {model_id!r}. Use exact provider/model-name from the catalog."
    return None


def infer_provider_from_model_id(model_id: str) -> Optional[str]:
    """Best-effort prefix-based provider inference.

    Returns 'nvidia', 'openrouter', or None if we can't tell.
    NIM-specific matches take precedence (since the same publisher
    sometimes appears in both catalogs but the NIM hosting is the
    point of using it as 'free-tier').
    """
    low = model_id.lower().strip()
    for prefix in _NVIDIA_PUBLISHER_PREFIXES:
        if low.startswith(prefix):
            return "nvidia"
    for prefix in _OPENROUTER_PUBLISHER_PREFIXES:
        if low.startswith(prefix):
            return "openrouter"
    return None


def resolve_model_and_keys(
    *,
    model_id: Optional[str],
    provider_hint: Optional[str],
    user_openrouter_key: Optional[str],
    user_nvidia_key: Optional[str],
    server_openrouter_key: str,
    server_nvidia_key: str,
    known_models: dict | None = None,
) -> ModelResolution:
    """One-stop validation of (model_id, provider, key) for a request.

    The caller passes in the server-side fallback keys so this module
    stays test-friendly (no hidden `get_settings()` call). When neither
    user-supplied nor server-supplied key is available for the resolved
    provider, returns an error pointing at the exact JSON field the user
    should populate.

    `known_models` is the MODEL_REGISTRY dict; pass in `MODEL_REGISTRY`
    from config.py to use registry hits to short-circuit provider
    inference. Free-text models that aren't in the registry still work —
    we just fall through to the prefix heuristic.
    """
    # 1. Shape check
    shape_err = validate_model_id_shape(model_id)
    if shape_err:
        return ModelResolution(
            valid=False,
            model_id=model_id or "",
            provider=None,
            error_category="missing_model_id" if not model_id else "bad_model_id_shape",
            error_message=shape_err,
            error_field="model.model_id",
        )

    # mypy / type narrow: model_id is non-empty after shape_err is None
    mid = model_id.strip()  # type: ignore[union-attr]

    # 2. Provider resolution: hint → registry → prefix heuristic
    provider: Optional[str] = None
    hint = provider_hint.strip().lower() if provider_hint else None
    if hint:
        if hint not in ("openrouter", "nvidia"):
            return ModelResolution(
                valid=False,
                model_id=mid,
                provider=None,
                error_category="bad_provider_hint",
                error_message=(f"provider hint must be 'openrouter' or 'nvidia', got {provider_hint!r}."),
                error_field="model.provider",
            )
        provider = hint
    elif known_models and mid in known_models:
        # Registry hit — use that even for "free-text" lookalikes
        prov_obj = known_models[mid].get("provider")
        provider = prov_obj.value if hasattr(prov_obj, "value") else str(prov_obj)
    else:
        provider = infer_provider_from_model_id(mid)

    if not provider:
        return ModelResolution(
            valid=False,
            model_id=mid,
            provider=None,
            error_category="ambiguous_provider",
            error_message=(
                f"Cannot infer which provider hosts model_id {mid!r}. Set "
                f"`model.provider` explicitly to 'openrouter' or 'nvidia' "
                f"so the router knows which key to use."
            ),
            error_field="model.provider",
        )

    # 3. Key presence
    if provider == "openrouter":
        if not (user_openrouter_key or server_openrouter_key):
            return ModelResolution(
                valid=False,
                model_id=mid,
                provider="openrouter",
                error_category="missing_key",
                error_message=(
                    f"Selected model {mid!r} routes to OpenRouter, but no "
                    f"OpenRouter API key is available. Either set "
                    f"`model.user_openrouter_key` in the request body (a "
                    f"`sk-or-v1-...` value from openrouter.ai/credits), or "
                    f"have the server admin set OPENROUTER_API_KEY."
                ),
                error_field="model.user_openrouter_key",
            )
    elif provider == "nvidia":
        if not (user_nvidia_key or server_nvidia_key):
            return ModelResolution(
                valid=False,
                model_id=mid,
                provider="nvidia",
                error_category="missing_key",
                error_message=(
                    f"Selected model {mid!r} routes to NVIDIA NIM, but no "
                    f"NVIDIA NIM API key is available. Either set "
                    f"`model.user_nvidia_key` in the request body (an "
                    f"`nvapi-...` value from build.nvidia.com), or have the "
                    f"server admin set NVIDIA_API_KEY."
                ),
                error_field="model.user_nvidia_key",
            )

    return ModelResolution(
        valid=True,
        model_id=mid,
        provider=provider,
        error_category=None,
        error_message=None,
        error_field=None,
    )
