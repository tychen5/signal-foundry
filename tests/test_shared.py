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
