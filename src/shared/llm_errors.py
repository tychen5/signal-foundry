"""
LLM error classification for user-friendly UI surfacing.

When a reviewer pastes a bad/expired/quota-exceeded API key, the worst UX is
"500 internal server error" with no hint of what to do. This module classifies
the underlying exception/HTTP status so the UI can show a specific actionable
message.

Categories (mapped to UI badges):
    invalid_key       — "API key rejected. Check the key copy/paste, or rotate it."
    rate_limit        — "Provider rate-limited the request. Try again in a few seconds."
    insufficient_credit — "Out of credits. Top up at openrouter.ai or rotate to NVIDIA NIM."
    quota_exhausted   — "Daily/monthly quota exhausted. Wait or rotate provider."
    timeout           — "Provider timed out. Network slow / try a smaller task."
    server_error      — "Provider returned a 5xx. Try again or switch model."
    no_response       — "Provider didn't respond. Network issue?"
    unknown           — Pass through the raw error string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMErrorInfo:
    category: str
    user_message: str
    raw_error: str
    suggested_action: str
    retryable: bool


_SIGNATURES: list[tuple[str, str]] = [
    # invalid key (case-insensitive)
    ("invalid_key", r"invalid[_\s-]*api[_\s-]*key|invalid[_\s-]*authentication|incorrect api key|unauthor[ie]zed.*api key"),
    ("invalid_key", r"\b401\b.*authentication|\b403\b.*forbidden"),
    ("invalid_key", r"key.*revoked|key.*expired|api key not found|no such key"),
    # rate limit
    ("rate_limit", r"\brate[_\s-]*limit|\b429\b|too many requests"),
    # credit / quota
    ("insufficient_credit", r"insufficient[_\s-]*credit|insufficient[_\s-]*balance|out of credit|requires credit|exceeded.*credit"),
    ("quota_exhausted", r"quota[_\s-]*exhausted|quota.*exceeded|usage[_\s-]*limit|monthly limit|daily limit"),
    # context length — hard-fail; user must switch to a bigger-context model
    ("context_length", r"context[_\s-]*length|context[_\s-]*window|maximum context|context.*exceed|tokens.*exceed|input.*too.*long|prompt.*too.*long|message.*too.*long"),
    # model not found (typo'd model id, deprecated model, region mismatch)
    ("model_not_found", r"model[_\s-]*not[_\s-]*found|invalid[_\s-]*model|model.*deprecated|unknown[_\s-]*model|no such model|model[_\s-]*does[_\s-]*not[_\s-]*exist"),
    # content / safety filter (some providers block prompts as policy
    # violations — we want users to know it's a content issue, not a key issue)
    ("content_filter", r"content[_\s-]*polic|content[_\s-]*filter|safety[_\s-]*polic|harmful[_\s-]*content|moderation|content.*flagged|prompt.*blocked|prompt_blocked|response.*blocked"),
    # timeout / network
    ("timeout", r"\btimeout\b|timed out|deadline exceeded"),
    ("no_response", r"connection.*reset|connection.*aborted|connection.*refused|name.*not.*resolved|ssl.*error"),
    # server-side
    ("server_error", r"\b50[0-9]\b|internal[_\s-]*server|service unavailable|bad gateway|gateway timeout"),
]

_USER_MESSAGES: dict[str, tuple[str, str, bool]] = {
    "invalid_key": (
        "API key rejected by the provider.",
        "Check that the key was copy-pasted correctly. For OpenRouter keys, the prefix is `sk-or-v1-`. For NVIDIA NIM, it's `nvapi-`. If the key is correct, rotate it on the provider's console and retry.",
        False,
    ),
    "rate_limit": (
        "Provider rate-limited the request.",
        "Wait 30-60 s and retry, or switch to a different model. NVIDIA NIM free tier ~4 calls/min/model; OpenRouter scales with credit balance.",
        True,
    ),
    "insufficient_credit": (
        "OpenRouter account is out of credits.",
        "Top up at https://openrouter.ai/credits — the smallest top-up ($1) covers ~50-100 LLM calls on Gemini 3.1 Pro Preview. Or switch to a free NVIDIA NIM model (Kimi K2.6 / GLM 5.1 / DeepSeek V4 Pro / MiniMax M2.7).",
        False,
    ),
    "quota_exhausted": (
        "Provider quota exhausted (daily or monthly).",
        "Wait until the quota window resets, or switch to a different provider/model. Use the model dropdown to rotate.",
        False,
    ),
    "timeout": (
        "Provider timed out before responding.",
        "Network slow or the model is busy. Retry with a smaller task or a faster model (Kimi K2.6 / Gemini 3.1 Pro). Avoid thinking-mode models for time-sensitive runs.",
        True,
    ),
    "no_response": (
        "Could not reach the provider's API.",
        "Network issue between Zeabur and the provider. Retry; if it persists, switch model or check provider status page.",
        True,
    ),
    "context_length": (
        "Prompt exceeds the model's context window.",
        "Switch to a longer-context model — Gemini 3.1 Pro Preview (1 M tokens) or Claude Opus 4.7 (200 K) handle the largest 10-K filings. Or shrink the input (skip use_vision for filings, or split the task).",
        False,
    ),
    "model_not_found": (
        "The selected model isn't available on this provider.",
        "Pick a different model from the dropdown. The defaults (Kimi K2.6 / GLM 5.1 / Gemini 3.1 Pro) are the most reliable.",
        False,
    ),
    "content_filter": (
        "Provider's content/safety filter blocked the request.",
        "Rephrase the task to avoid triggering policy filters, or switch to a less-filtered model. NVIDIA NIM models are typically more permissive than Anthropic on factual tasks.",
        False,
    ),
    "server_error": (
        "Provider returned a 5xx error.",
        "Transient provider issue. Retry once; if it persists, switch model.",
        True,
    ),
    "no_response_default": (
        "Unknown error from LLM provider.",
        "Inspect the raw error below and try a different model or refresh.",
        True,
    ),
}


def classify_llm_error(exc_or_str: object) -> LLMErrorInfo:
    """Map an exception (or its string form) to a user-actionable category."""
    raw = str(exc_or_str) if not isinstance(exc_or_str, str) else exc_or_str
    low = raw.lower()

    category = "unknown"
    for cat, pattern in _SIGNATURES:
        if re.search(pattern, low):
            category = cat
            break

    msg_key = category if category in _USER_MESSAGES else "no_response_default"
    user_msg, action, retryable = _USER_MESSAGES[msg_key]

    return LLMErrorInfo(
        category=category,
        user_message=user_msg,
        raw_error=raw[:600],
        suggested_action=action,
        retryable=retryable,
    )


def to_dict(info: LLMErrorInfo) -> dict:
    return {
        "category": info.category,
        "user_message": info.user_message,
        "raw_error": info.raw_error,
        "suggested_action": info.suggested_action,
        "retryable": info.retryable,
    }


def maybe_classify(error_field: Optional[str]) -> Optional[dict]:
    """Convenience: classify an error string if non-empty, else None."""
    if not error_field:
        return None
    return to_dict(classify_llm_error(error_field))
