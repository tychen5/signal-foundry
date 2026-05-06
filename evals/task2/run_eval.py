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
    """Score one browser agent result with deterministic checks."""
    checks: list[dict[str, Any]] = []

    # Check 1: Agent didn't crash
    checks.append({
        "name": "no_crash",
        "passed": result.status != "failed",
        "expected": "success or partial",
        "actual": result.status,
    })

    # Check 2: Agent produced a final answer
    checks.append({
        "name": "has_answer",
        "passed": bool(result.final_answer and result.final_answer.strip()),
        "expected": "non-empty answer",
        "actual": f"{len(result.final_answer)} chars" if result.final_answer else "empty",
    })

    # Check 3: Agent took steps (not zero-shot)
    checks.append({
        "name": "took_steps",
        "passed": result.total_steps > 0,
        "expected": "> 0 steps",
        "actual": result.total_steps,
    })

    # Check 4: Reasonable step count (not infinite loop)
    max_steps = case.get("input_data", {}).get("max_steps", 15)
    checks.append({
        "name": "reasonable_steps",
        "passed": result.total_steps <= max_steps,
        "expected": f"<= {max_steps}",
        "actual": result.total_steps,
    })

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
    }


async def _run_case(case: dict[str, Any], model_name: str | None) -> dict[str, Any]:
    """Run one eval case through the live browser agent."""
    started = time.time()
    try:
        agent = BrowserAgent(model_name=model_name, headless=True)
        result = await agent.run(
            task_description=case["input_data"]["task_description"],
            target_url=case["input_data"].get("target_url"),
            max_steps=case["input_data"].get("max_steps", 15),
        )
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
) -> dict[str, Any]:
    """Run all Task 2 eval cases.

    Args:
        inter_case_delay: Seconds to sleep between cases to avoid rate-limiting.
            NVIDIA NIM kimi-k2.6 allows ~4 calls/min on free tier; 5 s gap helps.
            Set to 0 for no delay (may hit 429 on batch runs).
    """
    import asyncio as _asyncio

    cases = _load_cases(eval_set)
    if skip_hard:
        cases = [c for c in cases if c.get("difficulty") != "hard"]

    scores = []
    for i, case in enumerate(cases):
        scores.append(await _run_case(case, model_name))
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
    args = parser.parse_args()

    payload = asyncio.run(
        run_eval(args.eval_set, args.results_dir, args.model, args.skip_hard, args.delay)
    )
    sys.stdout.write(json.dumps(payload["summary"], indent=2) + "\n")


if __name__ == "__main__":
    main()
