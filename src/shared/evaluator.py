"""
Evaluation Engine for Signal-Foundry.

Unified evaluation framework supporting:
1. Deterministic checks (exit codes, schema validity, char_range matching)
2. LLM-as-judge with configurable rubrics
3. Automatic failure taxonomy generation
4. Metric aggregation (success_rate, latency_p50/p95, cost_per_call)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.shared.logger import get_logger
from src.shared.schemas import EvalCase, EvalResult, FailureType

logger = get_logger("evaluator")


@dataclass
class EvalMetrics:
    """Aggregated evaluation metrics."""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    avg_confidence: float = 0.0
    failure_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p50_latency_ms": round(self.p50_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_confidence": round(self.avg_confidence, 4),
            "failure_distribution": self.failure_distribution,
        }


class DeterministicChecker:
    """
    Rule-based checks that don't require LLM.

    Examples:
    - Schema validation (all required fields present)
    - char_range matches actual content
    - Status codes are correct
    - Output is valid JSON
    """

    @staticmethod
    def check_json_schema(data: dict, required_fields: list[str]) -> tuple[bool, str]:
        """Check if data contains all required fields."""
        missing = [f for f in required_fields if f not in data]
        if missing:
            return False, f"Missing required fields: {missing}"
        return True, "All required fields present"

    @staticmethod
    def check_char_range(content: str, char_range: list[int], source_text: str) -> tuple[bool, str]:
        """Verify that char_range correctly maps to the expected content in source text."""
        if len(char_range) != 2:
            return False, f"char_range must have 2 elements, got {len(char_range)}"

        start, end = char_range
        if start < 0 or end > len(source_text) or start >= end:
            return False, f"Invalid char_range [{start}, {end}] for source of length {len(source_text)}"

        extracted = source_text[start:end]
        # Check if content is a substring of extracted (allowing for whitespace normalization)
        content_stripped = " ".join(content.split())
        extracted_stripped = " ".join(extracted.split())

        if content_stripped[:200] in extracted_stripped or extracted_stripped[:200] in content_stripped:
            return True, "char_range matches content"
        return False, "char_range does not match content"

    @staticmethod
    def check_non_empty(value: Any, field_name: str) -> tuple[bool, str]:
        """Check that a value is non-empty."""
        if value is None or (isinstance(value, (str, list, dict)) and len(value) == 0):
            return False, f"{field_name} is empty"
        return True, f"{field_name} is non-empty"

    @staticmethod
    def check_coverage(items: list[dict], expected_items: list[str], key: str = "item_number") -> tuple[bool, str]:
        """Check if all expected items are present in the output."""
        found = {item.get(key) for item in items}
        missing = [item for item in expected_items if item not in found]
        if missing:
            return False, f"Missing items: {missing}"
        return True, f"All {len(expected_items)} items found"


class EvaluationEngine:
    """
    Runs evaluation cases and aggregates results.

    Supports both deterministic checks and LLM-as-judge evaluation.
    """

    def __init__(self) -> None:
        self._results: list[EvalResult] = []

    async def run_eval_case(
        self,
        case: EvalCase,
        execution_func: Callable,
        checks: Optional[list[Callable]] = None,
    ) -> EvalResult:
        """
        Run a single evaluation case.

        Args:
            case: The test case to run
            execution_func: Function that executes the task (async)
            checks: Optional list of deterministic check functions

        Returns:
            EvalResult with pass/fail, confidence, and any failure details
        """
        start_time = time.time()

        try:
            # Execute the task
            output = await execution_func(case.input_data)
            latency_ms = (time.time() - start_time) * 1000

            # Run deterministic checks
            all_passed = True
            failure_notes = []

            if checks:
                for check_func in checks:
                    passed, message = check_func(output)
                    if not passed:
                        all_passed = False
                        failure_notes.append(message)

            result = EvalResult(
                case_id=case.case_id,
                passed=all_passed,
                actual_output=output if isinstance(output, (dict, list, str)) else str(output),
                confidence_score=1.0 if all_passed else 0.3,
                failure_type=None if all_passed else FailureType.PARSING_ERROR,
                latency_ms=latency_ms,
                notes="; ".join(failure_notes) if failure_notes else "All checks passed",
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            result = EvalResult(
                case_id=case.case_id,
                passed=False,
                confidence_score=0.0,
                failure_type=FailureType.LLM_ERROR,
                latency_ms=latency_ms,
                notes=f"Execution error: {str(e)}",
            )

        self._results.append(result)
        logger.info(
            "eval_case_completed",
            case_id=case.case_id,
            passed=result.passed,
            latency_ms=round(latency_ms, 1),
        )

        return result

    def compute_metrics(self, results: Optional[list[EvalResult]] = None) -> EvalMetrics:
        """Compute aggregate metrics from eval results."""
        results = results or self._results
        if not results:
            return EvalMetrics()

        latencies = sorted([r.latency_ms for r in results])
        total = len(results)
        passed = sum(1 for r in results if r.passed)

        # Failure distribution
        failure_dist: dict[str, int] = {}
        for r in results:
            if not r.passed and r.failure_type:
                ft = r.failure_type.value if hasattr(r.failure_type, "value") else str(r.failure_type)
                failure_dist[ft] = failure_dist.get(ft, 0) + 1

        # Percentile calculation
        p50_idx = max(0, int(total * 0.5) - 1)
        p95_idx = max(0, int(total * 0.95) - 1)

        return EvalMetrics(
            total_cases=total,
            passed=passed,
            failed=total - passed,
            success_rate=passed / total if total > 0 else 0.0,
            avg_latency_ms=sum(latencies) / total,
            p50_latency_ms=latencies[p50_idx],
            p95_latency_ms=latencies[p95_idx],
            total_cost_usd=sum(r.cost_usd for r in results),
            avg_confidence=sum(r.confidence_score for r in results) / total,
            failure_distribution=failure_dist,
        )

    def generate_report(self, results: Optional[list[EvalResult]] = None) -> dict:
        """Generate a complete evaluation report."""
        results = results or self._results
        metrics = self.compute_metrics(results)

        return {
            "summary": metrics.to_dict(),
            "results": [
                {
                    "case_id": r.case_id,
                    "passed": r.passed,
                    "confidence": r.confidence_score,
                    "failure_type": r.failure_type.value if r.failure_type else None,
                    "latency_ms": round(r.latency_ms, 1),
                    "cost_usd": round(r.cost_usd, 6),
                    "notes": r.notes,
                }
                for r in results
            ],
        }
