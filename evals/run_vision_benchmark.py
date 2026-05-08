"""Run OpenRouter vision on/off benchmark slices for Task 2 and Task 3."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from src.task2_browser.agent import BrowserAgent
from src.task3_sec.pipeline import extract_10k

OPENROUTER_VISION_MODELS = [
    "google/gemini-3.1-pro-preview",
    "anthropic/claude-opus-4.7",
    "openai/gpt-5.5",
]
DEFAULT_TASK2_CASES = [
    "t2_vision_chart_trend",
    "t2_vision_image_caption",
    "t2_vision_table_layout",
]
DEFAULT_TASK3_CASES = [
    "t3_american_express_1994_plain_text",
    "t3_asset_backed_trust_2011_not_applicable",
    "t3_kingsoft_cloud_2022_20f_duplicate_heading",
    "t3_enron_2000_complex_segments",
    "t3_lehman_2007_investment_bank",
]
ROOT = Path(__file__).resolve().parent


def _load_cases(path: Path, case_ids: list[str]) -> list[dict[str, Any]]:
    """Load selected eval cases by ID, preserving the requested order."""
    all_cases = json.loads(path.read_text(encoding="utf-8"))
    by_id = {case["case_id"]: case for case in all_cases}
    missing = [case_id for case_id in case_ids if case_id not in by_id]
    if missing:
        raise ValueError(f"Unknown case ids in {path}: {missing}")
    return [by_id[case_id] for case_id in case_ids]


async def _run_task2_case(
    case: dict[str, Any],
    model: str,
    use_vision: bool,
    timeout_s: float,
) -> dict[str, Any]:
    """Run one Task 2 case with one model and vision setting."""
    input_data = case["input_data"]
    try:
        agent = BrowserAgent(model_name=model, headless=True, use_vision=use_vision)
        result = await asyncio.wait_for(
            agent.run(
                task_description=input_data["task_description"],
                target_url=input_data.get("target_url"),
                max_steps=input_data.get("max_steps", 15),
            ),
            timeout=timeout_s,
        )
    except Exception as exc:
        return {
            "task": "task2",
            "case_id": case["case_id"],
            "model": model,
            "use_vision": use_vision,
            "status": "error",
            "ok": False,
            "steps": 0,
            "cost_usd": 0.0,
            "latency_ms": timeout_s * 1000,
            "llm_calls": 0,
            "failure_modes": [type(exc).__name__],
            "answer_preview": str(exc)[:160],
        }
    return {
        "task": "task2",
        "case_id": case["case_id"],
        "model": model,
        "use_vision": use_vision,
        "status": result.status,
        "ok": result.status in {"success", "not_found"},
        "steps": result.total_steps,
        "cost_usd": result.cost_usd,
        "latency_ms": result.total_duration_ms,
        "llm_calls": result.llm_calls,
        "failure_modes": result.failure_modes,
        "answer_preview": (result.final_answer or "")[:160],
    }


async def _run_task3_case(
    case: dict[str, Any],
    model: str,
    use_vision: bool,
    timeout_s: float,
    force_llm: bool,
) -> dict[str, Any]:
    """Run one Task 3 case with one model and vision setting."""
    input_data = case["input_data"]
    try:
        result = await asyncio.wait_for(
            extract_10k(
                cik=input_data.get("cik"),
                accession_number=input_data.get("accession_number"),
                filing_url=input_data.get("filing_url"),
                model_name=model,
                skip_llm=False,
                skip_xbrl=True,
                use_vision=use_vision,
                force_llm=force_llm,
            ),
            timeout=timeout_s,
        )
    except Exception as exc:
        return {
            "task": "task3",
            "case_id": case["case_id"],
            "model": model,
            "use_vision": use_vision,
            "status": "error",
            "ok": False,
            "items_extracted": 0,
            "items_total": 0,
            "cost_usd": 0.0,
            "latency_ms": timeout_s * 1000,
            "llm_calls": 0,
            "stages_used": [],
            "force_llm": force_llm,
            "error": str(exc)[:200],
        }
    meta = result.processing_metadata
    extracted = sum(1 for item in result.items if item.status.value != "not_found")
    conf_items = [item for item in result.items if item.confidence > 0.0]
    avg_conf = round(sum(i.confidence for i in conf_items) / len(conf_items), 3) if conf_items else 0.0
    return {
        "task": "task3",
        "case_id": case["case_id"],
        "model": model,
        "use_vision": use_vision,
        "status": "success",
        "ok": True,
        "items_extracted": extracted,
        "items_total": len(result.items),
        "avg_confidence": avg_conf,
        "cost_usd": meta.total_cost_usd,
        "latency_ms": meta.total_latency_ms,
        "llm_calls": meta.llm_calls,
        "stages_used": meta.stages_used,
        "force_llm": force_llm,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate benchmark rows by task/model/vision setting."""
    groups: dict[tuple[str, str, bool], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["task"], row["model"], row["use_vision"])
        groups.setdefault(key, []).append(row)

    summary = []
    for (task, model, use_vision), group in sorted(groups.items()):
        ok_count = sum(1 for row in group if row["ok"])
        summary.append(
            {
                "task": task,
                "model": model,
                "use_vision": use_vision,
                "cases": len(group),
                "ok_rate": round(ok_count / len(group), 3) if group else 0.0,
                "total_cost_usd": round(sum(row["cost_usd"] for row in group), 6),
                "avg_latency_ms": round(mean(row["latency_ms"] for row in group), 1),
                "llm_calls": sum(row["llm_calls"] for row in group),
            }
        )
    return {"groups": summary}


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    """Write a reviewer-readable Markdown benchmark report."""
    lines = [
        "# OpenRouter Vision On/Off Benchmark",
        "",
        f"- Run at: {payload['run_at']}",
        "- Models: Gemini 3.1 Pro, Claude Opus 4.7, GPT-5.5 via OpenRouter",
        "- Task 2 cases: vision-heavy browser tasks",
        "- Task 3 cases: legacy / foreign issuer / proxy-heavy filings",
        "",
        "## Summary",
        "",
        "| Task | Model | Vision | Cases | OK rate | Cost | Avg latency | LLM calls |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["summary"]["groups"]:
        lines.append(
            f"| {row['task']} | `{row['model']}` | {row['use_vision']} | "
            f"{row['cases']} | {row['ok_rate']:.3f} | ${row['total_cost_usd']:.6f} | "
            f"{row['avg_latency_ms']:.1f} ms | {row['llm_calls']} |"
        )

    lines.extend(["", "## Rows", ""])
    for row in payload["rows"]:
        if row["task"] == "task3":
            metric = (
                f"items={row.get('items_extracted')}/{row.get('items_total')}, "
                f"conf={row.get('avg_confidence', 'n/a')}"
            )
        else:
            metric = f"status={row.get('status')}, steps={row.get('steps')}"
        lines.append(
            f"- `{row['task']}` `{row['case_id']}` `{row['model']}` "
            f"vision={row['use_vision']}: {metric}, "
            f"cost=${row['cost_usd']:.6f}, latency={row['latency_ms']:.1f} ms"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_benchmark(
    task2_cases: list[dict[str, Any]],
    task3_cases: list[dict[str, Any]],
    models: list[str],
    include_task2: bool,
    include_task3: bool,
    timeout_s: float,
    force_llm_task3: bool,
) -> dict[str, Any]:
    """Run selected Task 2/Task 3 benchmark cases."""
    rows: list[dict[str, Any]] = []
    for model in models:
        for use_vision in (False, True):
            if include_task2:
                for case in task2_cases:
                    rows.append(await _run_task2_case(case, model, use_vision, timeout_s))
            if include_task3:
                for case in task3_cases:
                    rows.append(
                        await _run_task3_case(
                            case,
                            model,
                            use_vision,
                            timeout_s,
                            force_llm_task3,
                        )
                    )
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": {
            "timeout_s": timeout_s,
            "force_llm_task3": force_llm_task3,
        },
        "summary": _summarize(rows),
        "rows": rows,
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run OpenRouter vision on/off benchmark.")
    parser.add_argument("--task", choices=["task2", "task3", "both"], default="both")
    parser.add_argument("--models", nargs="+", default=OPENROUTER_VISION_MODELS)
    parser.add_argument("--task2-cases", nargs="+", default=DEFAULT_TASK2_CASES)
    parser.add_argument("--task3-cases", nargs="+", default=DEFAULT_TASK3_CASES)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "vision_results")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--force-llm-task3",
        action="store_true",
        help="Force Task 3 Stage 2 so vision on/off can be compared even on high-confidence filings.",
    )
    args = parser.parse_args()

    task2_cases = _load_cases(ROOT / "task2" / "eval_set.json", args.task2_cases)
    task3_cases = _load_cases(ROOT / "task3" / "eval_set.json", args.task3_cases)
    payload = asyncio.run(
        run_benchmark(
            task2_cases=task2_cases,
            task3_cases=task3_cases,
            models=args.models,
            include_task2=args.task in {"task2", "both"},
            include_task3=args.task in {"task3", "both"},
            timeout_s=args.timeout,
            force_llm_task3=args.force_llm_task3,
        )
    )

    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = args.results_dir / f"vision_benchmark_{stamp}.json"
    md_path = args.results_dir / f"vision_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(md_path, payload)
    sys.stdout.write(json.dumps(payload["summary"], indent=2) + "\n")


if __name__ == "__main__":
    main()
