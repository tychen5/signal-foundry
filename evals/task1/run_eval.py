"""
Run Task 1 CI/CD Skills evaluations.

Usage:
    python -m evals.task1.run_eval                   # live API mode
    python -m evals.task1.run_eval --direct          # import engine directly
    python -m evals.task1.run_eval --model <name>    # override LLM model
    python -m evals.task1.run_eval --skip-edge       # skip edge case scenarios

Scoring per case:
    no_crash            — result object returned without exception
    has_result          — result.result dict is non-empty on success
    correct_skill       — result.result["skill"] matches expected skill
    dry_run_no_tag      — build-and-release dry_run never sets tag_created=True
    error_case_detected — known-bad inputs returned FAILED status (not SUCCESS)
"""

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

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_SCENARIOS = EVAL_DIR / "scenarios.json"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _score_case(case: dict[str, Any], result_dict: dict[str, Any]) -> dict[str, Any]:
    """Score one CI/CD skill result with deterministic checks."""
    checks: list[dict[str, Any]] = []
    inp = case["input_data"]
    is_error_case = case.get("difficulty") == "edge_case"

    status = result_dict.get("status", "unknown")
    result_payload = result_dict.get("result") or {}
    error_msg = result_dict.get("error", "")

    # Check 1: no crash — the endpoint returned a parseable response
    checks.append({
        "name": "no_crash",
        "passed": "status" in result_dict,
        "expected": "has status field",
        "actual": status,
    })

    if is_error_case:
        # For error cases: expect FAILED status with an error message
        checks.append({
            "name": "error_case_detected",
            "passed": status == "failed" and bool(error_msg),
            "expected": "status=failed with error message",
            "actual": f"status={status}, error='{error_msg[:80]}'",
        })
    else:
        # Check 2: has_result — result payload is non-empty
        checks.append({
            "name": "has_result",
            "passed": status == "success" and bool(result_payload),
            "expected": "status=success with non-empty result",
            "actual": f"status={status}, result_keys={list(result_payload.keys())[:5]}",
        })

        # Check 3: correct_skill — resolved skill matches input
        expected_skill = inp.get("skill_name", "").lower().replace("_", "-")
        actual_skill = result_payload.get("skill", "")
        # Normalize: exact match or starts-with for fuzzy inputs
        skill_matched = (
            actual_skill == expected_skill
            or expected_skill in actual_skill
            or actual_skill in expected_skill
        )
        checks.append({
            "name": "correct_skill",
            "passed": skill_matched,
            "expected": expected_skill,
            "actual": actual_skill,
        })

        # Check 4: dry_run_no_tag — build-and-release with dry_run must NOT create a tag
        if "build" in expected_skill or "release" in expected_skill:
            dry_run_requested = inp.get("dry_run", True)
            tag_created = result_payload.get("tag_created", False)
            checks.append({
                "name": "dry_run_no_tag",
                "passed": not dry_run_requested or not tag_created,
                "expected": "no tag created when dry_run=True",
                "actual": f"dry_run={dry_run_requested}, tag_created={tag_created}",
            })

        # Check 5: has_summary — LLM produced a non-empty summary
        summary = result_payload.get("summary", "")
        checks.append({
            "name": "has_summary",
            "passed": bool(summary and len(summary) > 10),
            "expected": "non-empty LLM summary",
            "actual": f"{len(summary)} chars" if summary else "empty",
        })

    passed = all(c["passed"] for c in checks)

    return {
        "case_id": case["case_id"],
        "passed": passed,
        "checks": checks,
        "status": status,
        "skill_resolved": result_payload.get("skill", ""),
        "match_confidence": result_payload.get("match_confidence", 0),
        "language": result_payload.get("language", ""),
        "commit_sha": result_payload.get("commit_sha", ""),
        "cache_hit": result_payload.get("cache_hit", False),
        "summary_preview": (result_payload.get("summary", "") or "")[:200],
        "error": error_msg[:200] if error_msg else "",
        "latency_ms": result_dict.get("latency_ms", 0),
        "cost_usd": (result_dict.get("cost_metadata") or {}).get("cost_usd", 0),
    }


async def _run_case_direct(
    case: dict[str, Any],
    model_name: str | None,
) -> dict[str, Any]:
    """Run one case by importing the skill engine directly (no HTTP server required)."""
    from src.shared.logger import generate_trace_id
    from src.task1_cicd.schemas import SkillRunRequest
    from src.task1_cicd.skill_engine import run_skill
    from src.shared.schemas import ModelSelectionRequest

    inp = case["input_data"]
    trace_id = generate_trace_id()

    model_req = ModelSelectionRequest(model_id=model_name or "moonshotai/kimi-k2.6")
    request = SkillRunRequest(
        repo_url=inp["repo_url"],
        branch=inp.get("branch", "main"),
        skill_name=inp["skill_name"],
        dry_run=inp.get("dry_run", True),
        model=model_req,
    )

    started = time.monotonic()
    try:
        result = await run_skill(request, trace_id)
        return result.model_dump()
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }


async def _run_case_api(
    case: dict[str, Any],
    base_url: str,
    model_name: str | None,
) -> dict[str, Any]:
    """Run one case via the live HTTP API."""
    import httpx

    inp = case["input_data"]
    payload: dict[str, Any] = {
        "repo_url": inp["repo_url"],
        "branch": inp.get("branch", "main"),
        "skill_name": inp["skill_name"],
        "dry_run": inp.get("dry_run", True),
    }
    if model_name:
        payload["model"] = {"model_id": model_name}

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{base_url}/api/v1/skills/run", json=payload)
        if response.status_code == 200:
            return response.json()
        return {
            "status": "failed",
            "error": f"HTTP {response.status_code}: {response.text[:200]}",
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }


def _summarize(scores: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [s["latency_ms"] for s in scores if s["latency_ms"] > 0]
    costs = [s["cost_usd"] for s in scores]
    passed = [s for s in scores if s["passed"]]
    cache_hits = [s for s in scores if s.get("cache_hit")]

    # Per-check pass rates
    check_pass: dict[str, list[bool]] = {}
    for score in scores:
        for chk in score.get("checks", []):
            check_pass.setdefault(chk["name"], []).append(chk["passed"])
    check_rates = {k: round(sum(v) / len(v), 3) for k, v in check_pass.items()}

    return {
        "cases": len(scores),
        "passed": len(passed),
        "success_rate": round(len(passed) / len(scores), 3) if scores else 0.0,
        "cache_hit_rate": round(len(cache_hits) / len(scores), 3) if scores else 0.0,
        "avg_latency_ms": round(mean(latencies), 1) if latencies else 0.0,
        "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0, 1),
        "total_cost_usd": round(sum(costs), 6),
        "check_pass_rates": check_rates,
    }


def _write_markdown_report(
    payload: dict[str, Any],
    path: Path,
) -> None:
    """Write a human-readable Markdown report alongside the JSON."""
    s = payload["summary"]
    lines = [
        "# Task 1 CI/CD Skills — Eval Report",
        f"\n**Run at**: {payload['run_at']}",
        f"**Scenarios**: {payload['eval_set']}",
        "",
        "## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Cases | {s['cases']} |",
        f"| Passed | {s['passed']} / {s['cases']} |",
        f"| Success Rate | {s['success_rate']:.1%} |",
        f"| Cache Hit Rate | {s['cache_hit_rate']:.1%} |",
        f"| Avg Latency | {s['avg_latency_ms']:.0f} ms |",
        f"| P95 Latency | {s['p95_latency_ms']:.0f} ms |",
        f"| Total Cost | ${s['total_cost_usd']:.6f} |",
        "",
        "### Check Pass Rates",
        "| Check | Pass Rate |",
        "|-------|-----------|",
    ]
    for name, rate in s.get("check_pass_rates", {}).items():
        lines.append(f"| {name} | {rate:.1%} |")

    lines += ["", "## Case Results", ""]
    for score in payload["scores"]:
        icon = "✅" if score["passed"] else "❌"
        lines.append(f"### {icon} `{score['case_id']}`")
        lines.append(f"- Status: `{score['status']}`")
        if score.get("skill_resolved"):
            lines.append(f"- Skill: `{score['skill_resolved']}` (confidence: {score['match_confidence']:.0%})")
        if score.get("language"):
            lines.append(f"- Language: `{score['language']}`")
        if score.get("commit_sha"):
            lines.append(f"- Commit: `{score['commit_sha']}`")
        lines.append(f"- Latency: {score['latency_ms']:.0f} ms | Cost: ${score['cost_usd']:.6f}")
        if score.get("summary_preview"):
            lines.append(f"- Summary: _{score['summary_preview']}_")
        if score.get("error"):
            lines.append(f"- Error: `{score['error']}`")
        if score.get("cache_hit"):
            lines.append("- Cache: hit")
        lines.append("")
        for chk in score.get("checks", []):
            icon2 = "✅" if chk["passed"] else "❌"
            lines.append(f"  {icon2} **{chk['name']}**: expected `{chk['expected']}`, got `{chk['actual']}`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


async def run_eval(
    scenarios_path: Path,
    results_dir: Path,
    model_name: str | None = None,
    direct: bool = True,
    base_url: str = "http://localhost:8080",
    skip_edge: bool = False,
) -> dict[str, Any]:
    """Run all Task 1 eval scenarios."""
    cases = _load_scenarios(scenarios_path)
    if skip_edge:
        cases = [c for c in cases if c.get("difficulty") != "edge_case"]

    scores: list[dict[str, Any]] = []
    for case in cases:
        print(f"  Running {case['case_id']}...", flush=True)
        if direct:
            raw = await _run_case_direct(case, model_name)
        else:
            raw = await _run_case_api(case, base_url, model_name)
        score = _score_case(case, raw)
        scores.append(score)
        icon = "✅" if score["passed"] else "❌"
        print(f"    {icon} {score['status']} ({score['latency_ms']:.0f} ms)", flush=True)

    run_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "run_at": run_at,
        "eval_set": str(scenarios_path),
        "model": model_name or "moonshotai/kimi-k2.6",
        "mode": "direct" if direct else "api",
        "summary": _summarize(scores),
        "scores": scores,
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = results_dir / f"task1_eval_{stamp}.json"
    md_path = results_dir / f"task1_eval_{stamp}.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown_report(payload, md_path)

    print(f"\nResults saved: {json_path}", flush=True)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Task 1 CI/CD Skills evals.")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--direct", action="store_true", default=True,
                        help="Import engine directly (default). Use --api to hit live server.")
    parser.add_argument("--api", dest="direct", action="store_false",
                        help="Call the live HTTP API at --base-url.")
    parser.add_argument("--base-url", type=str, default="http://localhost:8080")
    parser.add_argument("--skip-edge", action="store_true",
                        help="Skip edge case scenarios (error handling tests).")
    args = parser.parse_args()

    print(f"Task 1 CI/CD Skills Eval — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Mode: {'direct engine' if args.direct else 'API'} | Model: {args.model or 'default'}\n")

    payload = asyncio.run(run_eval(
        args.scenarios,
        args.results_dir,
        model_name=args.model,
        direct=args.direct,
        base_url=args.base_url,
        skip_edge=args.skip_edge,
    ))

    sys.stdout.write("\n" + json.dumps(payload["summary"], indent=2) + "\n")


if __name__ == "__main__":
    main()
