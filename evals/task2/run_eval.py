"""Run Task 2 Browser Agent evaluations."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from src.task2_browser.agent import BrowserAgent
from src.task2_browser.schemas import AgentResult

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_EVAL_SET = EVAL_DIR / "eval_set.json"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    """Load eval cases from JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def _score_case(case: dict[str, Any], result: AgentResult) -> dict[str, Any]:
    """Score one browser agent result with deterministic checks.

    Two layers of check:

    1. Universal harness checks (always run): the agent didn't crash, took
       at least one step, didn't infinite-loop. These keep the eval honest
       on every case regardless of expected outcome.

    2. Per-case ``expected_outcome`` (optional, but recommended for every
       case): a deterministic correctness contract. Fields:

           expected_outcome.status               — "success" | "partial" | "not_found" | "unverified"
           expected_outcome.allowed_statuses     — list of statuses (any one passes)
           expected_outcome.answer_must_contain  — list of case-insensitive substrings
           expected_outcome.answer_must_not_contain — list of substrings
           expected_outcome.failure_modes_must_contain — list of failure-mode strings
           expected_outcome.min_steps / max_steps — optional bounds

    Added 2026-05-15 in response to interviewer concern Q3:
    "Task 2 eval 為什麼 not_found / partial / unverified 都算 pass?"
    The harness *intentionally* downgrades to not_found on silent-failure-
    guard cases, so a blanket "status==success" check would penalise the
    correct behaviour. But the original 4 generic checks were too permissive
    — they passed positive cases even when the agent returned the wrong
    answer. Per-case expected_outcome closes that gap deterministically (no
    LLM-as-judge involved).
    """
    checks: list[dict[str, Any]] = []
    expected = case.get("expected_outcome") or {}

    # ── Layer 1: universal harness checks ────────────────────────────
    checks.append(
        {
            "name": "no_crash",
            "passed": result.status != "failed",
            "expected": "not failed",
            "actual": result.status,
        }
    )

    # took_steps is waived when the fast path served the request (1 synthetic
    # step is recorded but the agent path was skipped entirely).
    fast_path_hit = bool((result.metadata or {}).get("fast_path", {}).get("hit"))
    min_steps = max(0, expected.get("min_steps", 1 if not fast_path_hit else 0))
    checks.append(
        {
            "name": "took_steps",
            "passed": result.total_steps >= min_steps,
            "expected": f">= {min_steps}",
            "actual": result.total_steps,
        }
    )

    max_steps = expected.get("max_steps") or case.get("input_data", {}).get("max_steps", 20)
    checks.append(
        {
            "name": "reasonable_steps",
            "passed": result.total_steps <= max_steps,
            "expected": f"<= {max_steps}",
            "actual": result.total_steps,
        }
    )

    # has_answer remains universal — even not_found cases should have a
    # human-readable explanation populated.
    checks.append(
        {
            "name": "has_answer",
            "passed": bool(result.final_answer and result.final_answer.strip()),
            "expected": "non-empty answer",
            "actual": f"{len(result.final_answer)} chars" if result.final_answer else "empty",
        }
    )

    # ── Layer 2: per-case correctness (deterministic, no LLM) ────────
    if expected:
        if "status" in expected:
            checks.append(
                {
                    "name": "expected_status",
                    "passed": result.status == expected["status"],
                    "expected": expected["status"],
                    "actual": result.status,
                }
            )
        if "allowed_statuses" in expected:
            allowed = set(expected["allowed_statuses"])
            checks.append(
                {
                    "name": "status_in_allowed",
                    "passed": result.status in allowed,
                    "expected": f"one of {sorted(allowed)}",
                    "actual": result.status,
                }
            )

        answer_lower = (result.final_answer or "").lower()
        for substr in expected.get("answer_must_contain", []):
            checks.append(
                {
                    "name": f"must_contain[{substr[:40]}]",
                    "passed": substr.lower() in answer_lower,
                    "expected": f"contains '{substr}'",
                    "actual": "present" if substr.lower() in answer_lower else "missing",
                }
            )
        for substr in expected.get("answer_must_not_contain", []):
            checks.append(
                {
                    "name": f"must_not_contain[{substr[:40]}]",
                    "passed": substr.lower() not in answer_lower,
                    "expected": f"missing '{substr}'",
                    "actual": "missing" if substr.lower() not in answer_lower else "present (banned)",
                }
            )
        for fm in expected.get("failure_modes_must_contain", []):
            present = any(fm in (m or "") for m in (result.failure_modes or []))
            checks.append(
                {
                    "name": f"failure_mode[{fm}]",
                    "passed": present,
                    "expected": f"failure_modes contains '{fm}'",
                    "actual": ",".join(result.failure_modes or []) or "(none)",
                }
            )

    passed = all(c["passed"] for c in checks)

    return {
        "case_id": case["case_id"],
        "passed": passed,
        "checks": checks,
        "status": result.status,
        "steps_taken": result.total_steps,
        "self_corrections": result.self_corrections,
        "healer_activations": result.healer_activations,
        "final_answer_preview": (result.final_answer or "")[:200],
        "failure_modes": result.failure_modes,
        "latency_ms": result.total_duration_ms,
        "cost_usd": result.cost_usd,
        "llm_calls": result.llm_calls,
        "fast_path_hit": fast_path_hit,
        "expected_outcome_present": bool(expected),
    }


async def _run_case(
    case: dict[str, Any],
    model_name: str | None,
    use_vision: bool = False,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Run one eval case through the live browser agent."""
    started = time.time()
    try:
        agent = BrowserAgent(
            model_name=model_name,
            headless=True,
            use_vision=use_vision,
        )
        coro = agent.run(
            task_description=case["input_data"]["task_description"],
            target_url=case["input_data"].get("target_url"),
            max_steps=case["input_data"].get("max_steps", 15),
        )
        result = await asyncio.wait_for(coro, timeout=timeout_s)
        return _score_case(case, result)
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "passed": False,
            "checks": [],
            "status": "error",
            "steps_taken": 0,
            "self_corrections": 0,
            "healer_activations": 0,
            "final_answer_preview": "",
            "failure_modes": [str(type(exc).__name__)],
            "latency_ms": round((time.time() - started) * 1000, 1),
            "cost_usd": 0.0,
            "llm_calls": 0,
            "error": str(exc),
        }


def _summarize(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate eval scores."""
    latencies = [s["latency_ms"] for s in scores]
    costs = [s["cost_usd"] for s in scores]
    passed = [s for s in scores if s["passed"]]

    return {
        "cases": len(scores),
        "passed": len(passed),
        "success_rate": round(len(passed) / len(scores), 3) if scores else 0.0,
        "avg_latency_ms": round(mean(latencies), 1) if latencies else 0.0,
        "total_cost_usd": round(sum(costs), 6),
        "avg_self_corrections": round(mean([s["self_corrections"] for s in scores]), 2) if scores else 0.0,
    }


async def run_eval(
    eval_set: Path,
    results_dir: Path,
    model_name: str | None = None,
    skip_hard: bool = False,
    inter_case_delay: float = 5.0,
    use_vision: bool = False,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Run all Task 2 eval cases.

    Args:
        inter_case_delay: Seconds to sleep between cases to avoid rate-limiting.
            NVIDIA NIM kimi-k2.6 allows ~4 calls/min on free tier; 5 s gap helps.
            Set to 0 for no delay (may hit 429 on batch runs).
        use_vision: Pass use_vision=True to the browser agent.
        timeout_s: Max seconds per case before forceful cancellation.
    """
    import asyncio as _asyncio

    cases = _load_cases(eval_set)
    if skip_hard:
        cases = [c for c in cases if c.get("difficulty") != "hard"]

    scores = []
    for i, case in enumerate(cases):
        scores.append(
            await _run_case(
                case,
                model_name,
                use_vision=use_vision,
                timeout_s=timeout_s,
            )
        )
        if inter_case_delay > 0 and i < len(cases) - 1:
            await _asyncio.sleep(inter_case_delay)

    run_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "run_at": run_at,
        "eval_set": str(eval_set),
        "summary": _summarize(scores),
        "scores": scores,
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = results_dir / f"task2_eval_{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return payload


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run Task 2 Browser Agent evals.")
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    parser.add_argument("--skip-hard", action="store_true")
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds between cases to avoid rate-limiting (default: 5.0)",
    )
    parser.add_argument(
        "--vision",
        action="store_true",
        help="Run with use_vision=True (only effective with OpenRouter vision models)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Max seconds per case before timeout (default: 120)",
    )
    args = parser.parse_args()

    payload = asyncio.run(
        run_eval(
            args.eval_set,
            args.results_dir,
            args.model,
            args.skip_hard,
            args.delay,
            args.vision,
            args.timeout,
        )
    )
    sys.stdout.write(json.dumps(payload["summary"], indent=2) + "\n")


if __name__ == "__main__":
    main()
