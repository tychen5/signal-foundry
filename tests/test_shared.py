"""Tests for shared infrastructure."""

import pytest

from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, TaskType


class TestSchemas:
    """Test shared Pydantic schemas."""

    def test_execution_result_creation(self):
        result = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            task=TaskType.CICD_SKILLS,
            trace_id="test123",
            result={"message": "ok"},
        )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.trace_id == "test123"

    def test_execution_result_with_error(self):
        result = ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.SEC_EXTRACTION,
            trace_id="err456",
            error="Something broke",
            failure_type=FailureType.PARSING_ERROR,
        )
        assert result.status == ExecutionStatus.FAILED
        assert result.failure_type == FailureType.PARSING_ERROR


class TestCostTracker:
    """Test cost tracking functionality."""

    def test_record_call(self):
        from src.shared.cost_tracker import CostTracker

        tracker = CostTracker()
        record = tracker.record_call(
            model="openai/gpt-5.5",
            tokens_in=1000,
            tokens_out=500,
            latency_ms=1200.0,
            task="task3_sec",
            operation="extract",
            trace_id="test789",
        )
        assert record.tokens_in == 1000
        assert record.cost_usd > 0

    def test_session_summary(self):
        from src.shared.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call("openai/gpt-5.5", 1000, 500, 1200, "task1", "lint")
        tracker.record_call("deepseek-ai/deepseek-v4-pro", 2000, 800, 800, "task3", "parse")

        summary = tracker.get_session_summary()
        assert summary["total_calls"] == 2
        assert summary["total_cost_usd"] > 0
        assert "task1" in summary["by_task"]

    def test_request_cost_so_far_sums_per_trace(self):
        """Cost-so-far returns just this trace's spend, not session total."""
        from src.shared.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call(
            "openai/gpt-5.5", 1000, 500, 100, "task3_sec", "extract", trace_id="t1"
        )
        tracker.record_call(
            "openai/gpt-5.5", 1000, 500, 100, "task3_sec", "extract", trace_id="t2"
        )
        c1 = tracker.request_cost_so_far("t1")
        c2 = tracker.request_cost_so_far("t2")
        assert c1 > 0 and c2 > 0
        assert abs(c1 - c2) < 1e-9
        assert tracker.request_cost_so_far("never-seen") == 0.0

    def test_check_request_budget_under_cap_passes(self):
        from src.shared.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call(
            "z-ai/glm-5.1", 100, 50, 100, "task3_sec", "extract", trace_id="t1"
        )
        # GLM 5.1 cost for 150 tokens is ~$0.00025 — well under default 0.50
        tracker.check_request_budget("t1", task="task3_sec")  # no raise

    def test_check_request_budget_over_cap_raises(self):
        """When cumulative cost exceeds the cap, BudgetExceededError carries
        actionable metadata for the router to convert to a structured error."""
        from src.shared.cost_tracker import BudgetExceededError, CostTracker

        tracker = CostTracker()
        # Burn $1.50 of Claude Opus on a task3 trace
        tracker.record_call(
            "anthropic/claude-opus-4.7",
            tokens_in=50_000,
            tokens_out=10_000,
            latency_ms=1000,
            task="task3_sec",
            operation="refine",
            trace_id="big_trace",
        )
        with pytest.raises(BudgetExceededError) as exc:
            tracker.check_request_budget(
                "big_trace", cap_usd=0.50, task="task3_sec"
            )
        err = exc.value
        assert err.trace_id == "big_trace"
        assert err.cost_so_far > err.cap_usd
        assert err.cap_usd == 0.50
        assert err.task == "task3_sec"

    def test_check_request_budget_default_caps_per_task(self):
        from src.shared.cost_tracker import (
            DEFAULT_BUDGET_CAP_USD,
            CostTracker,
        )

        tracker = CostTracker()
        for task in ("task1_cicd", "task2_browser", "task3_sec"):
            assert task in DEFAULT_BUDGET_CAP_USD
            assert DEFAULT_BUDGET_CAP_USD[task] > 0
        # No spend → no raise even with default cap
        tracker.check_request_budget("nonexistent", task="task3_sec")

    def test_check_request_budget_disabled_with_zero_cap(self):
        """cap_usd=0 disables the check — useful for benchmarks."""
        from src.shared.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call(
            "anthropic/claude-opus-4.7",
            tokens_in=999_999,
            tokens_out=999_999,
            latency_ms=1000,
            task="task3_sec",
            operation="refine",
            trace_id="big",
        )
        # cap=0 → no-op even with massive spend
        tracker.check_request_budget("big", cap_usd=0.0, task="task3_sec")


class TestHarness:
    """Test harness engine."""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        from src.shared.harness import execute_with_harness

        async def good_func():
            return "success"

        result = await execute_with_harness(good_func, step_name="test_step")
        assert result == "success"

    @pytest.mark.asyncio
    async def test_fast_fail(self):
        from src.shared.harness import FastFailError, execute_with_harness

        async def bad_input():
            raise FastFailError("Invalid input")

        with pytest.raises(FastFailError):
            await execute_with_harness(bad_input, step_name="test_fail")


class TestEvaluator:
    """Test evaluation engine."""

    def test_deterministic_check_schema(self):
        from src.shared.evaluator import DeterministicChecker

        passed, msg = DeterministicChecker.check_json_schema(
            {"name": "test", "value": 42},
            ["name", "value"],
        )
        assert passed

    def test_deterministic_check_missing(self):
        from src.shared.evaluator import DeterministicChecker

        passed, msg = DeterministicChecker.check_json_schema(
            {"name": "test"},
            ["name", "value"],
        )
        assert not passed
        assert "value" in msg


class TestUserKeyContextvars:
    """Per-request user-key contextvars in src/llm_provider.py.

    Routers call set_user_keys() at the start of every request so that
    get_llm() — invoked deep inside agents/healers/refiners — picks up the
    user-supplied key without each call site needing to thread it through.
    """

    def test_set_and_clear_openrouter(self):
        from src.llm_provider import (
            _user_openrouter_key_ctx,
            clear_user_keys,
            set_user_keys,
        )

        clear_user_keys()
        assert _user_openrouter_key_ctx.get() is None
        set_user_keys(openrouter="sk-or-v1-test")
        assert _user_openrouter_key_ctx.get() == "sk-or-v1-test"
        clear_user_keys()
        assert _user_openrouter_key_ctx.get() is None

    def test_set_nvidia_only(self):
        from src.llm_provider import (
            _user_nvidia_key_ctx,
            _user_openrouter_key_ctx,
            clear_user_keys,
            set_user_keys,
        )

        clear_user_keys()
        set_user_keys(nvidia="nvapi-test-1234")
        assert _user_nvidia_key_ctx.get() == "nvapi-test-1234"
        # OpenRouter key should remain unset
        assert _user_openrouter_key_ctx.get() is None
        clear_user_keys()

    def test_get_llm_reads_contextvar_when_arg_absent(self):
        """get_llm() should consult the contextvar if no explicit key is passed."""
        from src.llm_provider import clear_user_keys, get_llm, set_user_keys

        clear_user_keys()
        # Use NVIDIA-hosted model; supply a dummy NVIDIA key via contextvar.
        # We don't actually call the network — just confirm get_llm doesn't
        # raise the "API key required" ValueError.
        set_user_keys(nvidia="nvapi-fake-but-non-empty")
        try:
            llm = get_llm("moonshotai/kimi-k2.6")
            # If we got here, the contextvar key was accepted.
            assert llm is not None
        finally:
            clear_user_keys()

    def test_explicit_arg_wins_over_contextvar(self):
        """Explicit user_*_key argument should take precedence over the contextvar."""
        from langchain_openai import ChatOpenAI

        from src.llm_provider import clear_user_keys, get_llm, set_user_keys

        clear_user_keys()
        set_user_keys(nvidia="nvapi-from-ctx")
        try:
            llm = get_llm(
                "moonshotai/kimi-k2.6", user_nvidia_key="nvapi-from-explicit-arg"
            )
            assert isinstance(llm, ChatOpenAI)
            # The api_key on the wrapper is a SecretStr — coerce to string and check
            assert "from-explicit-arg" in str(llm.openai_api_key.get_secret_value())
        finally:
            clear_user_keys()


class TestJSONExtractor:
    """Tests for src.shared.llm_utils.extract_json_object / extract_json_array.

    These pin the LLM-output-shape robustness work — if a model misbehaves
    (smart quotes, prose preamble, ```json fences, truncation), the
    extractor should still recover the JSON object instead of forcing
    fragile regex fallbacks downstream.
    """

    def test_plain_json_object(self):
        from src.shared.llm_utils import extract_json_object
        result = extract_json_object('{"action": "click", "target": "button"}')
        assert result == {"action": "click", "target": "button"}

    def test_markdown_fenced_json(self):
        from src.shared.llm_utils import extract_json_object
        result = extract_json_object('```json\n{"a": 1, "b": 2}\n```')
        assert result == {"a": 1, "b": 2}

    def test_markdown_fenced_no_lang(self):
        from src.shared.llm_utils import extract_json_object
        result = extract_json_object('```\n{"a": 1}\n```')
        assert result == {"a": 1}

    def test_leading_prose(self):
        from src.shared.llm_utils import extract_json_object
        # The original "first { ... last }" regex would fail on this if there
        # were stray braces in the prose. The balanced extractor handles it.
        result = extract_json_object('Here is the JSON: {"action": "done", "value": "result"}')
        assert result == {"action": "done", "value": "result"}

    def test_trailing_prose(self):
        from src.shared.llm_utils import extract_json_object
        result = extract_json_object('{"a": 1}\n\nThis represents the next action.')
        assert result == {"a": 1}

    def test_smart_quotes(self):
        from src.shared.llm_utils import extract_json_object
        # Some models leak smart quotes — extract_json_object normalises them
        result = extract_json_object('{“action”: “navigate”}')
        assert result == {"action": "navigate"}

    def test_nested_braces(self):
        from src.shared.llm_utils import extract_json_object
        result = extract_json_object('{"meta": {"nested": true}, "x": 1}')
        assert result == {"meta": {"nested": True}, "x": 1}

    def test_braces_in_string(self):
        from src.shared.llm_utils import extract_json_object
        result = extract_json_object('{"reasoning": "use { and } as quotes", "ok": true}')
        assert result == {"reasoning": "use { and } as quotes", "ok": True}

    def test_returns_none_on_garbage(self):
        from src.shared.llm_utils import extract_json_object
        assert extract_json_object("just some prose, no json here") is None

    def test_returns_none_on_empty(self):
        from src.shared.llm_utils import extract_json_object
        assert extract_json_object("") is None
        assert extract_json_object("   \n  ") is None

    def test_returns_none_on_array_when_object_expected(self):
        from src.shared.llm_utils import extract_json_object
        # extract_json_object only returns objects, not arrays
        assert extract_json_object("[1, 2, 3]") is None

    def test_array_extractor(self):
        from src.shared.llm_utils import extract_json_array
        result = extract_json_array('```json\n[{"a": 1}, {"b": 2}]\n```')
        assert result == [{"a": 1}, {"b": 2}]

    def test_array_with_leading_prose(self):
        from src.shared.llm_utils import extract_json_array
        result = extract_json_array('Found these items: [{"x": 1}]')
        assert result == [{"x": 1}]


class TestLLMProviderJSONMode:
    """Verifies that json_mode (response_format=json_object) is correctly
    applied to plain models and SKIPPED for thinking-mode models that have
    extra_body set (otherwise the chat-template kwargs and response_format
    interact badly on NIM and the model returns silent empty content).
    """

    def test_json_mode_enabled_for_kimi(self):
        from src.llm_provider import get_llm
        llm = get_llm("moonshotai/kimi-k2.6", user_nvidia_key="nvapi-fake", json_mode=True)
        assert (llm.model_kwargs or {}).get("response_format") == {"type": "json_object"}

    def test_json_mode_skipped_for_glm_thinking(self):
        from src.llm_provider import get_llm
        # GLM 5.1 has extra_body for thinking-mode toggles; json_mode must skip
        llm = get_llm("z-ai/glm-5.1", user_nvidia_key="nvapi-fake", json_mode=True)
        assert "response_format" not in (llm.model_kwargs or {})

    def test_json_mode_skipped_for_deepseek_thinking(self):
        from src.llm_provider import get_llm
        llm = get_llm(
            "deepseek-ai/deepseek-v4-pro", user_nvidia_key="nvapi-fake", json_mode=True
        )
        assert "response_format" not in (llm.model_kwargs or {})

    def test_json_mode_default_is_off(self):
        from src.llm_provider import get_llm
        llm = get_llm("moonshotai/kimi-k2.6", user_nvidia_key="nvapi-fake")
        assert "response_format" not in (llm.model_kwargs or {})

    def test_json_mode_enabled_for_openrouter_models(self):
        from src.llm_provider import get_llm
        for model_id in (
            "google/gemini-3.1-pro-preview",
            "anthropic/claude-opus-4.7",
            "openai/gpt-5.5",
        ):
            llm = get_llm(model_id, user_openrouter_key="sk-or-fake", json_mode=True)
            assert (llm.model_kwargs or {}).get("response_format") == {
                "type": "json_object"
            }, f"json_mode should fire for {model_id}"

    def test_request_timeout_configured(self):
        from src.llm_provider import get_llm
        llm = get_llm("moonshotai/kimi-k2.6", user_nvidia_key="nvapi-fake")
        # Default 180 s; surfaced as request_timeout on the underlying ChatOpenAI
        assert llm.request_timeout == 180.0
