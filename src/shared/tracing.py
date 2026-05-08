"""
LangSmith tracing helpers.

Goal: get rich, structured traces for every task pipeline without forcing
LangSmith on users who don't want it. Strategy:

1. The OpenAI-compat path through `langchain_openai.ChatOpenAI` already
   auto-traces every chat completion when the LANGSMITH_* env vars are
   set in src/main.py's lifespan. That covers ~80% of the trace value.
2. This module adds optional `@traced` decorators on the *task-level*
   functions (`extract_10k`, `BrowserAgent.run`, `run_skill`) so each
   request shows up as a single root span in LangSmith with metadata
   (model, trace_id, cik/repo/task_description) attached.
3. When LangSmith is NOT configured, `@traced` is a no-op — the
   decorator returns the underlying function unchanged. Zero overhead
   for users without an api_key.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional


def _langsmith_enabled() -> bool:
    """LangSmith is active if both api_key and tracing flag are set."""
    return bool(os.environ.get("LANGSMITH_API_KEY")) and (
        os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
        or os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    )


def traced(
    name: Optional[str] = None,
    run_type: str = "chain",
    tags: Optional[list[str]] = None,
):
    """Decorator that wraps a function in a LangSmith run when enabled.

    Returns the original function unchanged when LangSmith env vars are
    absent — no import cost, no trace overhead, no api_key required.

    Args:
        name: Display name in the LangSmith UI (defaults to func.__name__)
        run_type: "chain" | "tool" | "retriever" | "llm". "chain" is the
            sensible default for task-level orchestrators.
        tags: List of string tags for filtering in the UI.
    """
    def decorator(func: Callable) -> Callable:
        if not _langsmith_enabled():
            return func

        try:
            from langsmith import traceable as _lt
        except ImportError:
            return func

        return _lt(
            name=name or func.__name__,
            run_type=run_type,
            tags=tags or [],
        )(func)

    return decorator


def attach_metadata(metadata: dict[str, Any]) -> None:
    """Best-effort: attach metadata to the *current* LangSmith run.

    Used so the trace UI shows model_name, trace_id, etc. on each span
    without coupling the call sites to the langsmith SDK directly.
    No-op if LangSmith isn't enabled or there's no active run.
    """
    if not _langsmith_enabled():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree
        run = get_current_run_tree()
        if run is not None:
            run.add_metadata(metadata)
    except Exception:
        pass


def trace_url(trace_id: str) -> Optional[str]:
    """Return None — LangSmith doesn't expose stable URLs by project name.

    LangSmith requires both an org-id and a project-id (UUIDs) to build a
    valid project URL, neither of which we can derive from the project
    NAME alone. Earlier versions returned a guessed URL that always 404'd
    on the live site. The UI now shows the internal trace_id as a
    copy-able chip instead — accurate, and the user can paste it into
    LangSmith's search bar themselves if they have access to the project.
    """
    return None
