"""Run Task 3 SEC 10-K extraction evaluations against official SEC filings."""

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

from src.shared.schemas import FailureType
from src.task3_sec.pipeline import extract_10k
from src.task3_sec.schemas import ExtractionResult, ItemStatus

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_EVAL_SET = EVAL_DIR / "eval_set.json"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    """Load eval cases from JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def _score_case(case: dict[str, Any], result: ExtractionResult) -> dict[str, Any]:
    """Score one extraction result with deterministic checks."""
    assertions = case.get("assertions", {})
    # An item counts as "extracted" if it has substantive content OR has a
    # legitimate non-extracted status (incorporated_by_reference / not_applicable
    # / reserved). Treating those as failures penalises filings that correctly
    # mark items as N/A or proxy-incorporated.
    extracted_items = [
        item
        for item in result.items
        if item.status != ItemStatus.NOT_FOUND and (item.content_text.strip() or item.status != ItemStatus.EXTRACTED)
    ]
    item_by_number = {item.item_number: item for item in result.items}
    allow_missing = set(assertions.get("allow_missing_recent_items", []))

    checks: list[dict[str, Any]] = []
    min_items = assertions.get("min_items_extracted", 0)
    checks.append(
        {
            "name": "min_items_extracted",
            "passed": len(extracted_items) >= min_items,
            "expected": min_items,
            "actual": len(extracted_items),
        }
    )

    for required in assertions.get("required_items", []):
        item = item_by_number.get(required)
        present = bool(item and item.status != ItemStatus.NOT_FOUND)
        checks.append(
            {
                "name": f"required_item_{required}",
                "passed": present,
                "expected": "present",
                "actual": item.status.value if item else "missing",
            }
        )

    for item_number, expected_status in assertions.get("expected_status_items", {}).items():
        item = item_by_number.get(item_number)
        checks.append(
            {
                "name": f"status_item_{item_number}",
                "passed": bool(item and item.status.value == expected_status),
                "expected": expected_status,
                "actual": item.status.value if item else "missing",
            }
        )

    validation_report = result.processing_metadata.validation_report
    if validation_report:
        checks.append(
            {
                "name": "pipeline_validation",
                "passed": bool(validation_report.get("overall_valid", False)),
                "expected": True,
                "actual": validation_report.get("overall_valid"),
            }
        )

    passed = all(check["passed"] for check in checks)
    missing_items = [
        item.item_number
        for item in result.items
        if item.status == ItemStatus.NOT_FOUND and item.item_number not in allow_missing
    ]

    # Compute average confidence for extracted items (shows LLM/vision benefit even on pass cases)
    conf_items = [item for item in result.items if item.confidence > 0.0]
    avg_confidence = round(sum(i.confidence for i in conf_items) / len(conf_items), 3) if conf_items else 0.0

    return {
        "case_id": case["case_id"],
        "passed": passed,
        "checks": checks,
        "items_returned": len(result.items),
        "items_extracted": len(extracted_items),
        "missing_items": missing_items,
        "status_counts": _status_counts(result),
        "avg_confidence": avg_confidence,
        "latency_ms": result.processing_metadata.total_latency_ms,
        "cost_usd": result.processing_metadata.total_cost_usd,
        "llm_calls": result.processing_metadata.llm_calls,
        "stages_used": result.processing_metadata.stages_used,
    }


def _status_counts(result: ExtractionResult) -> dict[str, int]:
    """Count item statuses in an extraction result."""
    counts = {status.value: 0 for status in ItemStatus}
    for item in result.items:
        counts[item.status.value] += 1
    return counts


def _classify_failure(case_score: dict[str, Any]) -> str | None:
    """Map deterministic check failures to the shared failure taxonomy."""
    if case_score["passed"]:
        return None
    if case_score["items_extracted"] == 0:
        return FailureType.PARSING_ERROR.value
    if case_score["missing_items"]:
        return FailureType.MISSING_SECTION.value
    return FailureType.PARSING_ERROR.value


async def _run_case(
    case: dict[str, Any],
    allow_llm: bool,
    skip_xbrl: bool,
    use_vision: bool = False,
    force_llm: bool = False,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Run one eval case through the live Task 3 pipeline."""
    started = time.time()
    try:
        coro = extract_10k(
            cik=case["input_data"].get("cik"),
            accession_number=case["input_data"].get("accession_number"),
            filing_url=case["input_data"].get("filing_url"),
            skip_llm=not allow_llm and not force_llm,
            skip_xbrl=skip_xbrl,
            use_vision=use_vision,
            force_llm=force_llm,
        )
        result = await asyncio.wait_for(coro, timeout=timeout_s)
        score = _score_case(case, result)
        score["failure_type"] = _classify_failure(score)
        score["error"] = None
        return score
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "passed": False,
            "checks": [],
            "items_returned": 0,
            "items_extracted": 0,
            "missing_items": [],
            "status_counts": {},
            "latency_ms": round((time.time() - started) * 1000, 1),
            "cost_usd": 0.0,
            "llm_calls": 0,
            "stages_used": [],
            "failure_type": FailureType.PARSING_ERROR.value,
            "error": str(exc),
        }


def _summarize(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate eval scores into report-level metrics."""
    latencies = [score["latency_ms"] for score in scores]
    costs = [score["cost_usd"] for score in scores]
    passed = [score for score in scores if score["passed"]]
    failure_types: dict[str, int] = {}
    for score in scores:
        failure_type = score.get("failure_type")
        if failure_type:
            failure_types[failure_type] = failure_types.get(failure_type, 0) + 1

    confidences = [score["avg_confidence"] for score in scores if score.get("avg_confidence", 0) > 0]
    llm_triggered = sum(1 for score in scores if score.get("llm_calls", 0) > 0)

    return {
        "cases": len(scores),
        "passed": len(passed),
        "success_rate": round(len(passed) / len(scores), 3) if scores else 0.0,
        "avg_latency_ms": round(mean(latencies), 1) if latencies else 0.0,
        "avg_cost_usd": round(mean(costs), 6) if costs else 0.0,
        "total_cost_usd": round(sum(costs), 6),
        "avg_confidence": round(mean(confidences), 3) if confidences else 0.0,
        "llm_triggered_cases": llm_triggered,
        "failure_types": failure_types,
    }


def _write_markdown_report(report_path: Path, payload: dict[str, Any]) -> None:
    """Write a concise Markdown report for interview/review readability."""
    summary = payload["summary"]
    lines = [
        "# Task 3 SEC 10-K Eval Report",
        "",
        f"- Run at: {payload['run_at']}",
        f"- Cases: {summary['cases']}",
        f"- Passed: {summary['passed']}",
        f"- Success rate: {summary['success_rate']}",
        f"- Average latency ms: {summary['avg_latency_ms']}",
        f"- Total cost USD: {summary['total_cost_usd']}",
        f"- Average confidence: {summary.get('avg_confidence', 'n/a')}",
        f"- LLM triggered cases: {summary.get('llm_triggered_cases', 0)}",
        f"- Failure types: {summary['failure_types']}",
        "",
        "## Cases",
        "",
    ]
    for score in payload["scores"]:
        status = "PASS" if score["passed"] else "FAIL"
        llm_flag = f", llm_calls={score.get('llm_calls', 0)}" if score.get('llm_calls', 0) > 0 else ""
        lines.append(
            f"- {status} `{score['case_id']}`: items_extracted={score['items_extracted']}, "
            f"conf={score.get('avg_confidence', 'n/a')}, "
            f"missing={score['missing_items']}, latency_ms={score['latency_ms']}"
            f"{llm_flag}, failure={score.get('failure_type')}"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_eval(
    eval_set: Path,
    results_dir: Path,
    allow_llm: bool,
    skip_xbrl: bool,
    use_vision: bool = False,
    force_llm: bool = False,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Run all Task 3 eval cases and persist JSON/Markdown reports."""
    cases = _load_cases(eval_set)
    scores = []
    for case in cases:
        scores.append(
            await _run_case(
                case,
                allow_llm=allow_llm,
                skip_xbrl=skip_xbrl,
                use_vision=use_vision,
                force_llm=force_llm,
                timeout_s=timeout_s,
            )
        )

    run_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "run_at": run_at,
        "eval_set": str(eval_set),
        "mode": {
            "allow_llm": allow_llm,
            "skip_xbrl": skip_xbrl,
            "use_vision": use_vision,
            "force_llm": force_llm,
            "timeout_s": timeout_s,
        },
        "summary": _summarize(scores),
        "scores": scores,
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = results_dir / f"task3_eval_{stamp}.json"
    md_path = results_dir / f"task3_eval_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown_report(md_path, payload)

    return payload


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run Task 3 SEC 10-K evals.")
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--allow-llm", action="store_true", help="Allow LLM boundary refinement.")
    parser.add_argument("--skip-xbrl", action="store_true", help="Skip XBRL cross-validation.")
    parser.add_argument(
        "--force-llm", action="store_true", help="Force Stage 2 LLM refinement even on high-confidence filings."
    )
    parser.add_argument(
        "--vision", action="store_true", help="Pass use_vision=True (only effective with vision-capable models)."
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="Max seconds per case before timeout (default: 300)."
    )
    args = parser.parse_args()

    payload = asyncio.run(
        run_eval(
            eval_set=args.eval_set,
            results_dir=args.results_dir,
            allow_llm=args.allow_llm,
            skip_xbrl=args.skip_xbrl,
            use_vision=args.vision,
            force_llm=args.force_llm,
            timeout_s=args.timeout,
        )
    )
    sys.stdout.write(json.dumps(payload["summary"], indent=2) + "\n")


if __name__ == "__main__":
    main()
