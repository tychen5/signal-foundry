"""
Structured Logging for Signal-Foundry.

Uses structlog for JSON-formatted, trace-ID-tagged logs.
Every operation gets a unique execution_id for end-to-end tracing.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

import structlog

# Context variable for per-request trace ID
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output and trace ID binding."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str, **kwargs: Any) -> structlog.BoundLogger:
    """Get a structured logger bound to a component name and trace ID."""
    trace_id = _trace_id.get() or generate_trace_id()
    return structlog.get_logger().bind(
        component=component,
        trace_id=trace_id,
        **kwargs,
    )


def generate_trace_id() -> str:
    """Generate a new unique trace ID and set it in context."""
    trace_id = str(uuid.uuid4())[:12]
    _trace_id.set(trace_id)
    return trace_id


def set_trace_id(trace_id: str) -> None:
    """Set the trace ID for the current context."""
    _trace_id.set(trace_id)
