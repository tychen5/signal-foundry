"""
Cost Tracker for Signal-Foundry.

Every LLM call must be tracked. Provides per-request and aggregate metrics
for token usage, latency, and estimated cost. Exposed via /metrics endpoint.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from src.shared.logger import get_logger

logger = get_logger("cost_tracker")

# Approximate cost per 1K tokens (USD) — update as pricing changes
COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "openai/gpt-5.5": {"input": 0.005, "output": 0.015},
    "anthropic/claude-opus-4.7": {"input": 0.015, "output": 0.075},
    "google/gemini-3.1-pro-preview": {"input": 0.00125, "output": 0.005},
    "moonshotai/kimi-k2.6": {"input": 0.002, "output": 0.006},
    "z-ai/glm-5.1": {"input": 0.001, "output": 0.003},
    "deepseek-ai/deepseek-v4-pro": {"input": 0.001, "output": 0.003},
    "minimaxai/minimax-m2.7": {"input": 0.002, "output": 0.006},
}

# Default cost if model not in registry
DEFAULT_COST = {"input": 0.003, "output": 0.010}


@dataclass
class LLMCallRecord:
    """Record of a single LLM call."""

    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    task: str  # e.g., "task1_cicd", "task2_browser", "task3_sec"
    operation: str  # e.g., "plan", "extract", "validate"
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""


class CostTracker:
    """
    Tracks LLM usage across the application.

    Thread-safe via append-only list. Provides aggregate metrics
    and per-request cost estimation.
    """

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []

    def record_call(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        task: str,
        operation: str,
        trace_id: str = "",
    ) -> LLMCallRecord:
        """Record an LLM call and compute its cost."""
        cost_rates = COST_PER_1K_TOKENS.get(model, DEFAULT_COST)
        cost_usd = (
            (tokens_in / 1000) * cost_rates["input"]
            + (tokens_out / 1000) * cost_rates["output"]
        )

        record = LLMCallRecord(
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            task=task,
            operation=operation,
            trace_id=trace_id,
        )
        self._records.append(record)

        logger.info(
            "llm_call_recorded",
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round(latency_ms, 1),
            cost_usd=round(cost_usd, 6),
            task=task,
            operation=operation,
        )

        return record

    def get_session_summary(self) -> dict:
        """Get aggregate metrics for the current session."""
        if not self._records:
            return {
                "total_calls": 0,
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "total_cost_usd": 0.0,
                "avg_latency_ms": 0.0,
                "by_task": {},
                "by_model": {},
            }

        total_calls = len(self._records)
        total_tokens_in = sum(r.tokens_in for r in self._records)
        total_tokens_out = sum(r.tokens_out for r in self._records)
        total_cost = sum(r.cost_usd for r in self._records)
        avg_latency = sum(r.latency_ms for r in self._records) / total_calls

        # Group by task
        by_task: dict = {}
        for r in self._records:
            if r.task not in by_task:
                by_task[r.task] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_task[r.task]["calls"] += 1
            by_task[r.task]["cost_usd"] += r.cost_usd
            by_task[r.task]["tokens"] += r.tokens_in + r.tokens_out

        # Group by model
        by_model: dict = {}
        for r in self._records:
            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "cost_usd": 0.0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["cost_usd"] += r.cost_usd

        return {
            "total_calls": total_calls,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_cost_usd": round(total_cost, 6),
            "avg_latency_ms": round(avg_latency, 1),
            "by_task": by_task,
            "by_model": by_model,
        }

    def get_request_cost(self, trace_id: str) -> dict:
        """Get cost breakdown for a specific request by trace ID."""
        records = [r for r in self._records if r.trace_id == trace_id]
        if not records:
            return {"trace_id": trace_id, "calls": 0, "cost_usd": 0.0}

        return {
            "trace_id": trace_id,
            "calls": len(records),
            "tokens_in": sum(r.tokens_in for r in records),
            "tokens_out": sum(r.tokens_out for r in records),
            "cost_usd": round(sum(r.cost_usd for r in records), 6),
            "latency_ms": round(sum(r.latency_ms for r in records), 1),
            "models_used": list({r.model for r in records}),
            "operations": [r.operation for r in records],
        }


# Singleton instance
_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get or create the singleton CostTracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
