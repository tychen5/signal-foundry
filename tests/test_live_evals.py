"""Opt-in live eval tests for reviewer-grade end-to-end checks.

Run with:
    RUN_LIVE_EVALS=1 pytest tests/test_live_evals.py -v

These tests intentionally hit real websites / SEC EDGAR and may use LLM
budget. They are skipped by default so normal CI stays deterministic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_EVALS") != "1",
    reason="Set RUN_LIVE_EVALS=1 to run live browser/SEC evals.",
)


def _load_case(path: str, case_id: str) -> dict[str, Any]:
    """Load one eval case by id."""
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    for case in cases:
        if case["case_id"] == case_id:
            return case
    raise AssertionError(f"Case not found: {case_id}")


@pytest.mark.asyncio
async def test_task2_live_eval_case_with_timeout() -> None:
    """Run one real BrowserAgent eval case, not just UI/render smoke."""
    from evals.task2.run_eval import _run_case

    case_id = os.environ.get("LIVE_TASK2_CASE", "t2_error_recovery_404")
    case = _load_case("evals/task2/eval_set.json", case_id)
    score = await _run_case(
        case,
        model_name=os.environ.get("LIVE_EVAL_MODEL"),
        use_vision=os.environ.get("LIVE_EVAL_USE_VISION") == "1",
        timeout_s=float(os.environ.get("LIVE_EVAL_TIMEOUT", "120")),
    )

    assert score["status"] != "error", score.get("error")
    assert score["steps_taken"] > 0
    assert score["latency_ms"] <= float(os.environ.get("LIVE_EVAL_TIMEOUT", "120")) * 1000


@pytest.mark.asyncio
async def test_task3_live_eval_case_with_optional_force_llm() -> None:
    """Run one real SEC extraction eval with timeout and optional forced LLM."""
    from evals.task3.run_eval import _run_case

    case_id = os.environ.get("LIVE_TASK3_CASE", "t3_apple_2023")
    force_llm = os.environ.get("LIVE_EVAL_FORCE_LLM") == "1"
    case = _load_case("evals/task3/eval_set.json", case_id)
    score = await _run_case(
        case,
        allow_llm=force_llm or os.environ.get("LIVE_EVAL_ALLOW_LLM") == "1",
        skip_xbrl=True,
        use_vision=os.environ.get("LIVE_EVAL_USE_VISION") == "1",
        force_llm=force_llm,
        timeout_s=float(os.environ.get("LIVE_EVAL_TIMEOUT", "180")),
    )

    assert score["error"] is None, score["error"]
    assert score["items_returned"] >= 20
    if force_llm:
        assert "llm_refine" in score["stages_used"]
