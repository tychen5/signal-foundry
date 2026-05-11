"""Tests for the LLM error classifier — surfaces user-actionable messages."""

from __future__ import annotations

from src.shared.llm_errors import (
    classify_llm_error,
    classify_with_stage,
    extract_http_status,
    maybe_classify,
)


class TestErrorClassification:
    def test_invalid_key_401(self):
        info = classify_llm_error("Error code: 401 - {'message': 'Invalid API key'}")
        assert info.category == "invalid_key"
        assert "rejected" in info.user_message.lower()
        assert info.retryable is False

    def test_invalid_key_explicit(self):
        info = classify_llm_error("invalid_api_key: provided key is malformed")
        assert info.category == "invalid_key"

    def test_revoked_key(self):
        info = classify_llm_error("API key has been revoked. Generate a new one.")
        assert info.category == "invalid_key"

    def test_rate_limit_429(self):
        info = classify_llm_error("Error code: 429 - Too Many Requests")
        assert info.category == "rate_limit"
        assert info.retryable is True
        assert "rate" in info.user_message.lower()
        assert extract_http_status("Error code: 429 - Too Many Requests") == 429

    def test_insufficient_credit(self):
        info = classify_llm_error("Insufficient credits to complete this request")
        assert info.category == "insufficient_credit"
        assert "openrouter" in info.suggested_action.lower()

    def test_quota_exhausted(self):
        info = classify_llm_error("monthly quota exceeded for this account")
        assert info.category == "quota_exhausted"

    def test_timeout(self):
        info = classify_llm_error("ReadTimeout: timed out reading response body")
        assert info.category == "timeout"
        assert info.retryable is True

    def test_no_response(self):
        info = classify_llm_error("ConnectionResetError: connection reset by peer")
        assert info.category == "no_response"

    def test_server_error_502(self):
        info = classify_llm_error("HTTP 502 Bad Gateway from upstream")
        assert info.category == "server_error"

    def test_unknown_error_falls_through(self):
        info = classify_llm_error("Some weird error nobody saw before")
        assert info.category == "unknown"
        # Still produces a usable user message
        assert info.user_message
        assert info.suggested_action

    def test_maybe_classify_handles_none(self):
        assert maybe_classify(None) is None
        assert maybe_classify("") is None

    def test_maybe_classify_returns_dict(self):
        d = maybe_classify("Error code: 429")
        assert d is not None
        assert d["category"] == "rate_limit"
        assert d["retryable"] is True
        assert d["status_code"] == 429
        assert d["status_label"] == "429 Rate Limit Exceeded"

    def test_raw_error_truncated(self):
        # Very long error must not blow up the response payload
        long = "x" * 2000
        info = classify_llm_error(long)
        assert len(info.raw_error) <= 600

    def test_context_length_exceeded_openai_form(self):
        info = classify_llm_error(
            "This model's maximum context length is 128000 tokens. However, your messages resulted in 145000 tokens."
        )
        assert info.category == "context_length"
        assert info.retryable is False
        assert "context window" in info.user_message.lower()

    def test_context_length_exceeded_alt_phrasing(self):
        info = classify_llm_error("Input prompt is too long for this model")
        assert info.category == "context_length"

    def test_model_not_found_typo(self):
        info = classify_llm_error("Model not found: openai/gpt-5.5-typo")
        assert info.category == "model_not_found"
        assert info.retryable is False

    def test_model_deprecated(self):
        info = classify_llm_error("The model 'gpt-3.5-turbo-0301' has been deprecated.")
        assert info.category == "model_not_found"

    def test_content_filter_blocked(self):
        info = classify_llm_error("Your request was flagged by our content policy and has been blocked.")
        assert info.category == "content_filter"
        assert info.retryable is False
        assert "filter" in info.user_message.lower() or "polic" in info.user_message.lower()

    def test_content_filter_safety(self):
        info = classify_llm_error("Response blocked due to safety policy violation.")
        assert info.category == "content_filter"

    def test_classify_with_stage_includes_status_and_model(self):
        d = classify_with_stage(
            "HTTP 404 model not found",
            stage="browser_plan",
            provider="openrouter",
            model_id="unknown/model",
        )
        assert d["stage"] == "browser_plan"
        assert d["provider"] == "openrouter"
        assert d["model_id"] == "unknown/model"
        assert d["status_code"] == 404
        assert d["status_label"] == "404 Not Found"
        assert d["category"] == "model_not_found"
