"""
Harness Engine for Signal-Foundry.

Three-layer fault tolerance:
1. Fast-fail: Input validation, schema checks
2. Retry with backoff: Transient errors, rate limits
3. Strategy replacement: Fallback to alternative approach

Plus: circuit breaker, execution ID tracking, and structured logging per step.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.shared.logger import get_logger

T = TypeVar("T")
logger = get_logger("harness")


class HarnessError(Exception):
    """Base error for harness operations."""

    def __init__(self, message: str, failure_type: str = "unknown", recoverable: bool = False):
        super().__init__(message)
        self.failure_type = failure_type
        self.recoverable = recoverable


class FastFailError(HarnessError):
    """Input validation failed — do not retry."""

    def __init__(self, message: str, failure_type: str = "invalid_input"):
        super().__init__(message, failure_type=failure_type, recoverable=False)


class TransientError(HarnessError):
    """Transient error — safe to retry."""

    def __init__(self, message: str, failure_type: str = "transient"):
        super().__init__(message, failure_type=failure_type, recoverable=True)


@dataclass
class ExecutionStep:
    """Record of a single step in a harness execution."""

    step_name: str
    status: str  # "success", "failed", "skipped"
    duration_ms: float = 0.0
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class ExecutionTrace:
    """Complete trace of a harness execution."""

    execution_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    steps: list[ExecutionStep] = field(default_factory=list)
    total_duration_ms: float = 0.0
    final_status: str = "pending"

    def add_step(self, step: ExecutionStep) -> None:
        self.steps.append(step)

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "steps": [
                {
                    "step_name": s.step_name,
                    "status": s.status,
                    "duration_ms": round(s.duration_ms, 1),
                    "error": s.error,
                    "retry_count": s.retry_count,
                }
                for s in self.steps
            ],
            "total_duration_ms": round(self.total_duration_ms, 1),
            "final_status": self.final_status,
        }


class CircuitBreaker:
    """
    Circuit breaker pattern: stops calling a failing service after N consecutive failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests fail immediately
    - HALF_OPEN: Testing if service recovered (after cooldown)
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"

    @property
    def state(self) -> str:
        if self._state == "open":
            if time.time() - self._last_failure_time > self.cooldown_seconds:
                self._state = "half_open"
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                "circuit_breaker_opened",
                failure_count=self._failure_count,
                threshold=self.failure_threshold,
            )

    def allow_request(self) -> bool:
        return self.state != "open"


async def execute_with_harness(
    func: Callable,
    *args: Any,
    step_name: str = "operation",
    max_retries: int = 3,
    fallback: Optional[Callable] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    trace: Optional[ExecutionTrace] = None,
    **kwargs: Any,
) -> Any:
    """
    Execute a function through the three-layer harness.

    Layer 1: Fast-fail (FastFailError → no retry)
    Layer 2: Retry with exponential backoff (TransientError → retry)
    Layer 3: Strategy replacement (fallback function)

    Args:
        func: The function to execute (sync or async)
        step_name: Name for trace logging
        max_retries: Max retry attempts for transient errors
        fallback: Alternative function if primary fails completely
        circuit_breaker: Circuit breaker instance
        trace: ExecutionTrace to append steps to

    Returns:
        Function result

    Raises:
        HarnessError: If all strategies exhausted
    """
    if trace is None:
        trace = ExecutionTrace()

    # Check circuit breaker
    if circuit_breaker and not circuit_breaker.allow_request():
        step = ExecutionStep(
            step_name=step_name,
            status="failed",
            error="Circuit breaker is open",
        )
        trace.add_step(step)
        raise HarnessError("Circuit breaker is open — service temporarily unavailable", "circuit_open")

    start_time = time.time()
    retry_count = 0
    last_error: Optional[Exception] = None

    # Layer 1 & 2: Try primary function with retries
    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            duration_ms = (time.time() - start_time) * 1000
            step = ExecutionStep(
                step_name=step_name,
                status="success",
                duration_ms=duration_ms,
                result=result,
                retry_count=retry_count,
            )
            trace.add_step(step)

            if circuit_breaker:
                circuit_breaker.record_success()

            return result

        except FastFailError:
            # Layer 1: No retry for validation errors
            raise

        except TransientError as e:
            # Layer 2: Retry with backoff
            retry_count += 1
            last_error = e
            if attempt < max_retries:
                wait_time = min(2 ** attempt, 30)  # Cap at 30 seconds
                logger.warning(
                    "retrying_transient_error",
                    step=step_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    wait_seconds=wait_time,
                    error=str(e),
                )
                await asyncio.sleep(wait_time)
            continue

        except Exception as e:
            last_error = e
            break

    # Primary function failed
    if circuit_breaker:
        circuit_breaker.record_failure()

    duration_ms = (time.time() - start_time) * 1000

    # Layer 3: Try fallback strategy
    if fallback is not None:
        logger.info("trying_fallback", step=step_name, primary_error=str(last_error))
        try:
            if asyncio.iscoroutinefunction(fallback):
                result = await fallback(*args, **kwargs)
            else:
                result = fallback(*args, **kwargs)

            step = ExecutionStep(
                step_name=f"{step_name}_fallback",
                status="success",
                duration_ms=(time.time() - start_time) * 1000,
                result=result,
                retry_count=retry_count,
            )
            trace.add_step(step)
            return result

        except Exception as fallback_error:
            logger.error("fallback_failed", step=step_name, error=str(fallback_error))

    # All strategies exhausted
    step = ExecutionStep(
        step_name=step_name,
        status="failed",
        duration_ms=duration_ms,
        error=str(last_error),
        retry_count=retry_count,
    )
    trace.add_step(step)

    error_msg = f"All strategies exhausted for {step_name}: {last_error}"
    raise HarnessError(error_msg, failure_type="all_strategies_exhausted")
