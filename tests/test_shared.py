"""Tests for shared infrastructure."""

import pytest
from src.shared.schemas import ExecutionStatus, FailureType, ExecutionResult, TaskType


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
        from src.shared.harness import execute_with_harness, FastFailError

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
