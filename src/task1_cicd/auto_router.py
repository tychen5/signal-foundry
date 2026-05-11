"""
Auto-Router: LLM-driven CI/CD skill orchestration.

PEPS loop = Plan → Execute → Postmortem → Synthesize.

  Plan       (LLM)  : query + hints + skill catalog → ordered skill plan
  Execute    (rules): existing skill_engine.run_skill(...) handles each skill
  Postmortem (LLM)  : after each skill, decide continue / add_skill / stop
  Synthesize (LLM)  : single-paragraph answer tying all results back to the query

Invariants:
  • A skill is never executed twice in the same loop (idempotency + cache key reuse).
  • The exclude-hint is hard-enforced both during plan and postmortem.
  • Hard caps on iterations + per-request budget guard against runaway loops.
  • All LLM calls go through cost_tracker so /metrics stays accurate.
  • All progress events are emitted via the same callback shape used by stream_run_skill.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from src.shared.cost_tracker import get_cost_tracker
from src.shared.llm_utils import coerce_message_text, extract_json_object
from src.shared.logger import get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, TaskType
from src.shared.tracing import attach_metadata, traced
from src.task1_cicd.schemas import (
    AutoRouterRequest,
    AutoRouterResult,
    AutoRouterStep,
    SkillRunRequest,
)
from src.task1_cicd.skill_registry import VALID_SKILLS

logger = get_logger("auto_router")

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "cicd"

# Default routing model — cheap NIM thinking-light model. The user can
# override per-request via AutoRouterRequest.model.model_id.
DEFAULT_ROUTER_MODEL = "moonshotai/kimi-k2.6"

# Skills that materially mutate the repo — never auto-pick without explicit
# user intent expressed in the query (the planner prompt enforces this, but
# we double-belt at the execution level too).
WRITE_CAPABLE_SKILLS = {"build-and-release"}

ProgressCallback = Callable[[dict], Awaitable[None]]


def _read_prompt(filename: str) -> str:
    path = PROMPT_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Auto-router prompt missing: {path}")
    return path.read_text(encoding="utf-8")


def _normalise_skill_list(raw: list[Any] | None) -> list[str]:
    """Coerce a list-of-strings hint to canonical skill names; drop unknowns silently."""
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        candidate = item.strip().lower()
        if candidate in VALID_SKILLS and candidate not in out:
            out.append(candidate)
    return out


def _looks_like_release_query(query: str) -> bool:
    """Heuristic — does the user's NL query plausibly mention release/ship/tag?"""
    q = query.lower()
    triggers = ("release", "ship it", "publish", "deploy", "tag", "version bump", "cut a version", "make a release")
    return any(t in q for t in triggers)


def _is_release_intent_explicit(query: str, include_hint: list[str]) -> bool:
    """Has the user expressed clear intent to run the write-capable build-and-release skill?

    Two equally-explicit signals count:
      1. The NL query mentions release / ship / publish / tag / etc. (existing heuristic).
      2. The user ticked the build-and-release chip in the include hint UI.

    Either alone is enough — the include-hint override matters specifically
    for the "no NL query, just chips" mode this user requested. Without it,
    `_sanitise_plan` would silently drop build-and-release even when the user
    explicitly asked for it.
    """
    if "build-and-release" in include_hint:
        return True
    return _looks_like_release_query(query)


def _derive_default_plan(
    include_hint: list[str],
    exclude_hint: list[str],
    max_skills: int,
    query: str,
) -> list[str]:
    """Build a deterministic plan for the no-LLM-call path (empty query).

    Rules (ordered):
      1. If the user supplied include_hint chips, that IS the plan. Respect their
         order, drop excludes, and gate build-and-release the same way the LLM
         path does (the hint counts as explicit release intent — see
         `_is_release_intent_explicit`).
      2. Otherwise fall back to the safe default pair (dependency-audit +
         security-scan), filtered by exclude_hint, capped at max_skills.
      3. Final defence-in-depth: if everything got filtered out (e.g. user
         excluded both default skills), return [dependency-audit] (or whatever
         survives) so the request still does *something* reproducible rather
         than failing opaquely.
    """
    release_explicit = _is_release_intent_explicit(query, include_hint)

    if include_hint:
        seen: set[str] = set()
        out: list[str] = []
        for s in include_hint:
            if s not in VALID_SKILLS or s in exclude_hint or s in seen:
                continue
            if s in WRITE_CAPABLE_SKILLS and not release_explicit:
                continue
            out.append(s)
            seen.add(s)
            if len(out) >= max_skills:
                break
        if out:
            return out
        # include_hint was provided but every entry got filtered
        # (e.g. user included only build-and-release with no release-intent
        # signal AND a release-intent signal — mutually exclusive but possible
        # if exclude also covers it). Fall through to the default path.

    candidates = [s for s in ("dependency-audit", "security-scan") if s not in exclude_hint]
    plan = candidates[: max(1, max_skills)]
    if plan:
        return plan

    # Both default skills excluded — pick the cheapest survivor.
    for fallback in ("lint-and-test", "build-and-release"):
        if fallback in exclude_hint:
            continue
        if fallback in WRITE_CAPABLE_SKILLS and not release_explicit:
            continue
        return [fallback]

    # User excluded literally everything. Honest signal back: empty plan,
    # the loop will record terminated_reason="plan_exhausted".
    return []


def _compact_findings(skill: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Boil a full skill result down to the few fields the router actually needs.

    The decide-step prompt sees this — it's the LLM's only window into the
    skill output, so we keep it tight (token cost) but informative."""
    if skill == "lint-and-test":
        return {
            "lint_passed": raw.get("lint_passed"),
            "lint_issue_count": raw.get("lint_issue_count", len(raw.get("lint_issues", []))),
            "test_passed": raw.get("test_passed"),
            "test_total": raw.get("test_total", 0),
            "test_failed": raw.get("test_failed_count", 0),
        }
    if skill == "dependency-audit":
        return {
            "total_dependencies": raw.get("total_dependencies", 0),
            "cve_count": len(raw.get("vulnerabilities", [])),
            "critical_count": raw.get("critical_count", 0),
            "high_count": raw.get("high_count", 0),
            "outdated_count": len(raw.get("outdated", [])),
        }
    if skill == "security-scan":
        return {
            "files_scanned": raw.get("files_scanned", 0),
            "finding_count": len(raw.get("findings", [])),
            "severity_counts": raw.get("severity_counts", {}),
        }
    if skill == "build-and-release":
        return {
            "current_version": raw.get("current_version"),
            "next_version": raw.get("next_version"),
            "version_bump": raw.get("version_bump"),
            "commits_since_tag": raw.get("commits_since_tag", 0),
            "tag_created": raw.get("tag_created", False),
        }
    return {}


def _aggregate_signals(steps: list[AutoRouterStep]) -> dict[str, int]:
    """Roll-up of headline numbers across all executed skills, for the synthesis prompt."""
    out = {
        "total_lint_issues": 0,
        "total_test_failures": 0,
        "total_cves": 0,
        "total_outdated": 0,
        "total_secrets": 0,
        "total_sast": 0,
    }
    for step in steps:
        raw = step.raw_result or {}
        skill = step.skill_executed
        if skill == "lint-and-test":
            out["total_lint_issues"] += int(raw.get("lint_issue_count", 0) or len(raw.get("lint_issues", []) or []))
            out["total_test_failures"] += int(raw.get("test_failed_count", 0) or 0)
        elif skill == "dependency-audit":
            out["total_cves"] += int(len(raw.get("vulnerabilities", []) or []))
            out["total_outdated"] += int(len(raw.get("outdated", []) or []))
        elif skill == "security-scan":
            findings = raw.get("findings", []) or []
            for f in findings:
                ftype = (f.get("finding_type") or "").lower() if isinstance(f, dict) else ""
                if ftype == "secret":
                    out["total_secrets"] += 1
                else:
                    out["total_sast"] += 1
    return out


# ──────────────────────────────────────────────────────────────────────────────
# LLM stages
# ──────────────────────────────────────────────────────────────────────────────


async def _llm_plan(
    request: AutoRouterRequest,
    trace_id: str,
) -> tuple[list[str], dict[str, str], str, float]:
    """Initial planning: pick the ordered skill set."""
    from src.llm_provider import get_llm

    template = _read_prompt("v1_auto_router_plan.txt")
    include_hint = _normalise_skill_list(request.include_skills_hint)
    exclude_hint = _normalise_skill_list(request.exclude_skills_hint)

    prompt = (
        template
        .replace("{user_query}", request.natural_language_query.strip())
        .replace("{repo_url}", request.repo_url)
        .replace("{branch}", request.branch)
        .replace("{dry_run}", "true" if request.dry_run else "false")
        .replace("{max_skills}", str(request.max_skills))
        .replace("{include_hint}", json.dumps(include_hint))
        .replace("{exclude_hint}", json.dumps(exclude_hint))
    )

    model = request.model.model_id or DEFAULT_ROUTER_MODEL
    llm = get_llm(
        model_name=model,
        user_openrouter_key=request.model.user_openrouter_key,
        user_nvidia_key=request.model.user_nvidia_key,
        temperature=0.0,
        max_tokens=600,
    )

    start = time.monotonic()
    response = await llm.ainvoke(prompt)
    latency_ms = (time.monotonic() - start) * 1000
    raw_text = coerce_message_text(getattr(response, "content", response))
    data = extract_json_object(raw_text) or {}

    plan_raw = data.get("plan") or []
    plan = _sanitise_plan(
        plan_raw,
        exclude_hint,
        request.max_skills,
        request.natural_language_query,
        include_hint=include_hint,
    )

    rationale = data.get("rationale_per_skill") or {}
    if not isinstance(rationale, dict):
        rationale = {}
    overall_intent = (data.get("overall_intent") or "").strip()
    confidence = float(data.get("confidence") or 0.5)

    tracker = get_cost_tracker()
    tracker.record_call(
        model=model,
        tokens_in=len(prompt) // 4,
        tokens_out=len(raw_text) // 4,
        latency_ms=latency_ms,
        task="task1_cicd",
        operation="auto_router_plan",
        trace_id=trace_id,
    )

    logger.info("auto_router_plan", plan=plan, confidence=confidence, trace_id=trace_id)
    return plan, rationale, overall_intent, confidence


def _sanitise_plan(
    raw_plan: list[Any],
    exclude_hint: list[str],
    max_skills: int,
    user_query: str,
    include_hint: Optional[list[str]] = None,
) -> list[str]:
    """Coerce the LLM's plan to a valid de-duplicated, exclude-respecting skill list.

    `include_hint` (when supplied) marks build-and-release as user-authorised
    even if the NL query is silent on release intent — equivalent to ticking
    the chip in the FE.
    """
    include_hint = include_hint or []
    release_explicit = _is_release_intent_explicit(user_query, include_hint)

    seen: set[str] = set()
    out: list[str] = []
    for item in raw_plan:
        if not isinstance(item, str):
            continue
        s = item.strip().lower()
        if s not in VALID_SKILLS or s in exclude_hint or s in seen:
            continue
        # Defence in depth: never auto-schedule build-and-release unless
        # release intent is explicit (NL query mentions release/ship/etc., OR
        # user ticked the build-and-release chip). The planner prompt enforces
        # the first half; this catches a model that ignores instructions.
        if s in WRITE_CAPABLE_SKILLS and not release_explicit:
            continue
        out.append(s)
        seen.add(s)
        if len(out) >= max_skills:
            break

    if not out:
        # Degenerate fallback — query was too ambiguous AND every candidate
        # got filtered. Default to the two cheap read-only skills.
        out = [s for s in ("dependency-audit", "security-scan") if s not in exclude_hint][: max(1, max_skills)]
    return out


async def _llm_decide(
    request: AutoRouterRequest,
    overall_intent: str,
    original_plan: list[str],
    executed_skills: list[str],
    remaining_plan: list[str],
    last_step: AutoRouterStep,
    iterations_used: int,
    cost_so_far: float,
    budget_cap: float,
    exclude_hint: list[str],
    trace_id: str,
    include_hint: Optional[list[str]] = None,
) -> tuple[str, Optional[str], str, float]:
    """After each skill, decide: continue / add_skill / stop."""
    from src.llm_provider import get_llm

    template = _read_prompt("v1_auto_router_decide.txt")
    findings_compact = _compact_findings(last_step.skill_executed, last_step.raw_result or {})

    # When the user gave no NL query, substitute the synthesized intent so the
    # decide-LLM still has something coherent to read instead of a blank line.
    query_for_prompt = request.natural_language_query.strip() or (
        f"(no natural-language query provided) {overall_intent}".strip()
    )

    prompt = (
        template
        .replace("{user_query}", query_for_prompt)
        .replace("{overall_intent}", overall_intent or "(not provided)")
        .replace("{repo_url}", request.repo_url)
        .replace("{branch}", request.branch)
        .replace("{original_plan}", json.dumps(original_plan))
        .replace("{executed_skills}", json.dumps(executed_skills))
        .replace("{remaining_plan}", json.dumps(remaining_plan))
        .replace("{iterations_used}", str(iterations_used))
        .replace("{max_iterations}", str(request.max_iterations))
        .replace("{cost_usd}", f"{cost_so_far:.4f}")
        .replace("{budget_cap_usd}", f"{budget_cap:.4f}")
        .replace("{last_skill}", last_step.skill_executed)
        .replace("{last_status}", last_step.status or "unknown")
        .replace("{last_summary}", (last_step.summary or "")[:600])
        .replace("{last_findings_compact}", json.dumps(findings_compact))
        .replace("{exclude_hint}", json.dumps(exclude_hint))
    )

    model = request.model.model_id or DEFAULT_ROUTER_MODEL
    llm = get_llm(
        model_name=model,
        user_openrouter_key=request.model.user_openrouter_key,
        user_nvidia_key=request.model.user_nvidia_key,
        temperature=0.0,
        max_tokens=300,
    )

    start = time.monotonic()
    response = await llm.ainvoke(prompt)
    latency_ms = (time.monotonic() - start) * 1000
    raw_text = coerce_message_text(getattr(response, "content", response))
    data = extract_json_object(raw_text) or {}

    action = (data.get("action") or "stop").strip().lower()
    if action not in {"continue", "add_skill", "stop"}:
        action = "stop"

    next_skill = data.get("next_skill")
    if isinstance(next_skill, str):
        next_skill = next_skill.strip().lower() or None
    else:
        next_skill = None

    # Defence: scrub illegal next_skill choices.
    include_hint_local = include_hint or []
    if next_skill is not None:
        if next_skill not in VALID_SKILLS:
            next_skill = None
        elif next_skill in executed_skills:
            next_skill = None
        elif next_skill in exclude_hint:
            next_skill = None
        elif next_skill in WRITE_CAPABLE_SKILLS and not _is_release_intent_explicit(
            request.natural_language_query, include_hint_local
        ):
            next_skill = None

    reasoning = (data.get("reasoning") or "").strip()
    confidence = float(data.get("confidence") or 0.5)

    tracker = get_cost_tracker()
    tracker.record_call(
        model=model,
        tokens_in=len(prompt) // 4,
        tokens_out=len(raw_text) // 4,
        latency_ms=latency_ms,
        task="task1_cicd",
        operation="auto_router_decide",
        trace_id=trace_id,
    )

    logger.info(
        "auto_router_decision",
        action=action,
        next_skill=next_skill,
        confidence=confidence,
        iterations_used=iterations_used,
        trace_id=trace_id,
    )
    return action, next_skill, reasoning, confidence


async def _llm_synthesize(
    request: AutoRouterRequest,
    steps: list[AutoRouterStep],
    trace_id: str,
) -> str:
    """Single-paragraph cross-skill answer, tied back to the user's question."""
    from src.llm_provider import get_llm

    if not steps:
        return "No skills executed — nothing to synthesize."

    template = _read_prompt("v1_auto_router_synthesize.txt")
    signals = _aggregate_signals(steps)

    per_skill_summaries_lines = []
    for s in steps:
        per_skill_summaries_lines.append(
            f"- {s.skill_executed} ({s.status or 'n/a'}): {(s.summary or '').strip()[:500]}"
        )
    per_skill_summaries = "\n".join(per_skill_summaries_lines)

    query_stripped = (request.natural_language_query or "").strip()
    if query_stripped:
        query_for_prompt = query_stripped
    else:
        # Empty-query mode — paraphrase what the user actually asked for via
        # the chips so the synthesizer doesn't open with "your question was: ".
        executed_names = ", ".join(s.skill_executed for s in steps) or "selected skills"
        query_for_prompt = (
            f"(no natural-language query was provided; the user requested a CI/CD "
            f"check using {executed_names})"
        )

    prompt = (
        template
        .replace("{user_query}", query_for_prompt)
        .replace("{repo_url}", request.repo_url)
        .replace("{branch}", request.branch)
        .replace("{executed_skills}", json.dumps([s.skill_executed for s in steps]))
        .replace("{per_skill_summaries}", per_skill_summaries)
        .replace("{total_lint_issues}", str(signals["total_lint_issues"]))
        .replace("{total_test_failures}", str(signals["total_test_failures"]))
        .replace("{total_cves}", str(signals["total_cves"]))
        .replace("{total_outdated}", str(signals["total_outdated"]))
        .replace("{total_secrets}", str(signals["total_secrets"]))
        .replace("{total_sast}", str(signals["total_sast"]))
    )

    model = request.model.model_id or DEFAULT_ROUTER_MODEL
    llm = get_llm(
        model_name=model,
        user_openrouter_key=request.model.user_openrouter_key,
        user_nvidia_key=request.model.user_nvidia_key,
        temperature=0.3,
        max_tokens=500,
    )

    start = time.monotonic()
    try:
        response = await llm.ainvoke(prompt)
    except Exception as e:
        logger.warning("auto_router_synthesize_failed", error=str(e))
        # Deterministic fallback so the FE always has *something* to show.
        skills_done = ", ".join(s.skill_executed for s in steps)
        if request.natural_language_query:
            tail = f"for query '{request.natural_language_query[:120]}'."
        else:
            tail = "from the user-selected skill chips."
        return (
            f"Auto-router executed {skills_done} {tail} "
            f"LLM synthesis unavailable — see per-skill summaries below."
        )
    latency_ms = (time.monotonic() - start) * 1000
    text = coerce_message_text(getattr(response, "content", response)).strip()

    tracker = get_cost_tracker()
    tracker.record_call(
        model=model,
        tokens_in=len(prompt) // 4,
        tokens_out=len(text) // 4,
        latency_ms=latency_ms,
        task="task1_cicd",
        operation="auto_router_synthesize",
        trace_id=trace_id,
    )

    if not text:
        # Thinking-mode model returned only reasoning_content, no answer body.
        return (
            f"Auto-router executed {len(steps)} skill(s); LLM synthesis empty. "
            f"See per-skill summaries below."
        )
    # Strip stray code fences if the model defied "no markdown".
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration loop
# ──────────────────────────────────────────────────────────────────────────────


@traced(name="task1_auto_router", tags=["task1", "auto_router"])
async def run_auto_router(
    request: AutoRouterRequest,
    trace_id: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> ExecutionResult:
    """Run the LLM-driven multi-skill orchestration loop end-to-end."""
    # Lazy import to avoid the cycle (skill_engine -> auto_router -> skill_engine).
    from src.task1_cicd.skill_engine import run_skill as engine_run_skill

    async def _emit(event: str, **payload) -> None:
        if not progress_callback:
            return
        try:
            await progress_callback({"event": event, **payload})
        except Exception as e:
            logger.warning("auto_router_emit_failed", error=str(e)[:120])

    attach_metadata({
        "trace_id": trace_id,
        "task": "task1_auto_router",
        "repo_url": request.repo_url,
        "branch": request.branch,
        "model_name": request.model.model_id if request.model else "default",
    })

    start_time = time.monotonic()
    tracker = get_cost_tracker()
    budget_cap = request.budget_cap_usd if request.budget_cap_usd and request.budget_cap_usd > 0 else None

    exclude_hint = _normalise_skill_list(request.exclude_skills_hint)
    include_hint = _normalise_skill_list(request.include_skills_hint)
    query_stripped = (request.natural_language_query or "").strip()
    has_query = bool(query_stripped)

    await _emit(
        "auto_router_start",
        repo=request.repo_url,
        branch=request.branch,
        query=request.natural_language_query,
        has_query=has_query,
        include_hint=include_hint,
        exclude_hint=exclude_hint,
        max_iterations=request.max_iterations,
        max_skills=request.max_skills,
        model=request.model.model_id if request.model else "default",
        dry_run=request.dry_run,
    )

    # ── PLAN ──────────────────────────────────────────────────────────────
    # Two paths:
    #   A. NL query provided → ask the LLM to plan (existing flow).
    #   B. NL query empty → derive the plan deterministically from the user's
    #      hint chips (or the safe default pair). Skips the plan LLM call
    #      entirely — pure cost win when the user already decided.
    if has_query:
        try:
            plan, rationale, overall_intent, plan_confidence = await _llm_plan(request, trace_id)
        except Exception as e:
            logger.error("auto_router_plan_failed", error=str(e), trace_id=trace_id, exc_info=True)
            return _fail_result(f"Auto-router plan failed: {e}", trace_id, start_time)
        plan_source = "llm"

        # If user provided an include hint, push those to the front (preserving order)
        # without disturbing the rest of the plan or duplicating skills.
        if include_hint:
            ordered: list[str] = [s for s in include_hint if s in plan]
            ordered.extend(s for s in plan if s not in ordered)
            plan = ordered[: request.max_skills]
    else:
        # Hint-only mode (no LLM plan call).
        plan = _derive_default_plan(include_hint, exclude_hint, request.max_skills, query_stripped)
        if include_hint:
            rationale = {s: "user explicitly selected this skill via the include-hint chip" for s in plan}
            overall_intent = (
                f"User did not provide a free-form query; running the user-selected skill set: "
                f"{', '.join(plan)}."
            )
        elif exclude_hint:
            rationale = {s: "default health-check skill (user only specified what to skip)" for s in plan}
            overall_intent = (
                f"User did not provide a query and only excluded {', '.join(exclude_hint)}; "
                f"running the default CI/CD health check on the remaining skills."
            )
        else:
            rationale = {s: "default health-check skill (no query, no hints)" for s in plan}
            overall_intent = (
                "User did not provide a query or hints; running the default CI/CD health check "
                "(dependency-audit + security-scan)."
            )
        plan_confidence = 1.0  # deterministic — no LLM ambiguity to discount
        plan_source = "hint" if include_hint else "default"

        if not plan:
            # User excluded literally everything. Don't burn LLM calls — return
            # a structured failure now.
            return _fail_result(
                "Auto-router has no skills to run: every available skill is in exclude_skills_hint.",
                trace_id,
                start_time,
            )

    await _emit(
        "plan_done",
        plan=plan,
        rationale=rationale,
        overall_intent=overall_intent,
        confidence=plan_confidence,
        plan_source=plan_source,
    )

    # ── EXECUTE + POSTMORTEM loop ────────────────────────────────────────
    steps: list[AutoRouterStep] = []
    executed_skills: list[str] = []
    remaining_plan = list(plan)
    iterations_used = 0
    terminated_reason = "router_stop"
    last_commit_sha = ""

    while True:
        # Loop guards
        if iterations_used >= request.max_iterations:
            terminated_reason = "iteration_cap"
            break
        if not remaining_plan:
            terminated_reason = "plan_exhausted"
            break
        if budget_cap is not None:
            if tracker.request_cost_so_far(trace_id) >= budget_cap:
                terminated_reason = "budget_cap"
                break

        next_skill = remaining_plan.pop(0)
        if next_skill in executed_skills:
            # Defence-in-depth: should never happen given the dedup in plan/decide.
            continue

        iterations_used += 1
        rationale_for_step = rationale.get(next_skill, "") if iterations_used == 1 or next_skill in plan else ""

        await _emit(
            "iteration_start",
            iteration=iterations_used,
            skill=next_skill,
            rationale=rationale_for_step,
        )

        # Wrap the inner skill engine's progress events so the FE can attribute
        # each event to the current router iteration.
        inner_iteration = iterations_used

        async def _inner_progress(event: dict) -> None:
            await _emit(
                "skill_progress",
                iteration=inner_iteration,
                skill=next_skill,
                inner=event,
            )

        skill_request = SkillRunRequest(
            repo_url=request.repo_url,
            branch=request.branch,
            skill_name=next_skill,
            dry_run=request.dry_run,
            model=request.model,
        )
        skill_start = time.monotonic()
        try:
            execution = await engine_run_skill(skill_request, trace_id, progress_callback=_inner_progress)
        except Exception as e:
            logger.error("auto_router_skill_crash", skill=next_skill, error=str(e), trace_id=trace_id, exc_info=True)
            execution = ExecutionResult(
                status=ExecutionStatus.FAILED,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                error=f"Skill {next_skill} crashed: {e}",
                failure_type=FailureType.SANDBOX_ERROR,
            )
        skill_latency = (time.monotonic() - skill_start) * 1000
        cost_for_this_skill = tracker.get_request_cost(trace_id).get("cost_usd", 0.0)

        raw_result = execution.result if isinstance(execution.result, dict) else None
        last_commit_sha = (raw_result or {}).get("commit_sha", last_commit_sha)
        cache_hit = bool((raw_result or {}).get("cache_hit", False))
        status_str = (raw_result or {}).get("status", execution.status.value if execution.status else "")
        summary_str = (raw_result or {}).get("summary", "") or ""

        step = AutoRouterStep(
            iteration=iterations_used,
            skill_executed=next_skill,
            rationale=rationale_for_step,
            status=str(status_str),
            summary=summary_str,
            cache_hit=cache_hit,
            cost_usd=float(cost_for_this_skill),  # cumulative cost ledger snapshot
            latency_ms=skill_latency,
            raw_result=raw_result,
        )
        steps.append(step)
        executed_skills.append(next_skill)

        await _emit(
            "iteration_skill_done",
            iteration=iterations_used,
            skill=next_skill,
            status=step.status,
            cache_hit=step.cache_hit,
            summary_preview=(summary_str or "")[:200],
            latency_ms=int(step.latency_ms),
        )

        # Hard stop if the skill outright failed — don't burn tokens deciding
        # what to do next, just terminate and synthesize what we have.
        if execution.status == ExecutionStatus.FAILED:
            step.decision_after = "stop"
            step.decision_reasoning = "previous skill failed; aborting loop"
            terminated_reason = "skill_failed"
            await _emit(
                "iteration_decision",
                iteration=iterations_used,
                action="stop",
                reasoning=step.decision_reasoning,
                next_skill=None,
                confidence=1.0,
            )
            break

        # Postmortem — let the LLM choose continue / add_skill / stop.
        if iterations_used >= request.max_iterations:
            step.decision_after = "stop"
            step.decision_reasoning = "iteration cap reached"
            terminated_reason = "iteration_cap"
            await _emit(
                "iteration_decision",
                iteration=iterations_used,
                action="stop",
                reasoning=step.decision_reasoning,
                next_skill=None,
                confidence=1.0,
            )
            break

        if budget_cap is not None and tracker.request_cost_so_far(trace_id) >= budget_cap:
            step.decision_after = "stop"
            step.decision_reasoning = "budget cap reached"
            terminated_reason = "budget_cap"
            await _emit(
                "iteration_decision",
                iteration=iterations_used,
                action="stop",
                reasoning=step.decision_reasoning,
                next_skill=None,
                confidence=1.0,
            )
            break

        try:
            action, next_choice, reasoning_str, decision_conf = await _llm_decide(
                request=request,
                overall_intent=overall_intent,
                original_plan=plan,
                executed_skills=executed_skills,
                remaining_plan=remaining_plan,
                last_step=step,
                iterations_used=iterations_used,
                cost_so_far=tracker.request_cost_so_far(trace_id),
                budget_cap=budget_cap or 0.30,
                exclude_hint=exclude_hint,
                trace_id=trace_id,
                include_hint=include_hint,
            )
        except Exception as e:
            logger.warning("auto_router_decide_failed", error=str(e), trace_id=trace_id)
            action, next_choice, reasoning_str, decision_conf = ("stop", None, f"decide step error: {e}", 0.0)

        step.decision_after = action
        step.decision_reasoning = reasoning_str
        step.decision_confidence = decision_conf

        await _emit(
            "iteration_decision",
            iteration=iterations_used,
            action=action,
            reasoning=reasoning_str,
            next_skill=next_choice,
            confidence=decision_conf,
        )

        if action == "stop":
            terminated_reason = "router_stop"
            break

        if action == "add_skill" and next_choice:
            # Drop everything from the planner's remaining_plan in favour of the
            # router's new pivot. This is the agentic moment: the router has
            # decided new evidence outweighs the original plan.
            remaining_plan = [next_choice]
            continue

        # action == "continue" → just loop with the unchanged remaining_plan.
        # Edge case: if remaining_plan is empty AND action is continue, we
        # fall through next iteration and hit the plan_exhausted guard.

    # ── SYNTHESIZE ───────────────────────────────────────────────────────
    await _emit("synthesize_start", model=request.model.model_id if request.model else "default")
    try:
        synthesis = await _llm_synthesize(request, steps, trace_id)
    except Exception as e:
        logger.warning("auto_router_synthesis_outer_failed", error=str(e), trace_id=trace_id)
        synthesis = (
            f"Synthesis failed ({e.__class__.__name__}); see per-skill summaries below."
        )
    await _emit("synthesize_done", synthesis_preview=synthesis[:240])

    elapsed = (time.monotonic() - start_time) * 1000
    cost_metadata = tracker.get_request_cost(trace_id)

    auto_result = AutoRouterResult(
        query=request.natural_language_query,
        overall_intent=overall_intent,
        initial_plan=plan,
        plan_confidence=plan_confidence,
        skills_executed=executed_skills,
        steps=steps,
        final_synthesis=synthesis,
        iterations_used=iterations_used,
        terminated_reason=terminated_reason,
        total_cost_usd=float(cost_metadata.get("cost_usd", 0.0)),
        total_latency_ms=elapsed,
        repo_url=request.repo_url,
        branch=request.branch,
        commit_sha=last_commit_sha,
        dry_run=request.dry_run,
    )

    # Per the demo brief, the FE highlights `skill_executed`. We surface BOTH
    # singular and list form so reviewers can grep for either spelling.
    payload = auto_result.model_dump(mode="json")
    payload["skill_executed"] = executed_skills

    await _emit(
        "auto_router_complete",
        skills_executed=executed_skills,
        terminated_reason=terminated_reason,
        iterations_used=iterations_used,
        total_cost_usd=auto_result.total_cost_usd,
        total_latency_ms=int(elapsed),
    )

    return ExecutionResult(
        status=ExecutionStatus.SUCCESS if executed_skills else ExecutionStatus.FAILED,
        task=TaskType.CICD_SKILLS,
        trace_id=trace_id,
        result=payload,
        cost_metadata=cost_metadata,
        latency_ms=elapsed,
    )


def _fail_result(error: str, trace_id: str, start_time: float) -> ExecutionResult:
    elapsed = (time.monotonic() - start_time) * 1000
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        task=TaskType.CICD_SKILLS,
        trace_id=trace_id,
        error=error,
        failure_type=FailureType.LLM_ERROR,
        latency_ms=elapsed,
    )
