"""
Task 1 Router: CI/CD Skills Engine API.

Endpoints for running GitHub CI/CD skills against repositories.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.shared.logger import generate_trace_id, get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, TaskType
from src.task1_cicd.schemas import (
    AutoRouterRequest,
    SkillListResponse,
    SkillRunRequest,
)

router = APIRouter()
logger = get_logger("task1_router")

_SKILL_CATALOG = [
    {
        "name": "lint-and-test",
        "description": "Run linting and test suites on a GitHub repository",
        "trigger_phrases": ["test this", "run tests", "check code quality", "lint", "run ci"],
        "scope": "read-only",
        "languages": ["python", "javascript"],
    },
    {
        "name": "build-and-release",
        "description": "Analyze git history, determine next version, and optionally create a GitHub release",
        "trigger_phrases": ["release", "ship it", "deploy", "publish", "new version"],
        "scope": "gated-write",
        "dry_run_default": True,
    },
    {
        "name": "dependency-audit",
        "description": "Audit dependencies for CVEs and outdated packages via OSV.dev",
        "trigger_phrases": ["audit deps", "check vulnerabilities", "CVE check", "outdated packages"],
        "scope": "read-only",
        "data_sources": ["OSV.dev", "PyPI", "npm"],
    },
    {
        "name": "security-scan",
        "description": "Scan source code for hardcoded secrets and SAST vulnerabilities",
        "trigger_phrases": ["scan for secrets", "SAST", "find leaked keys", "security audit"],
        "scope": "read-only",
        "tools": ["regex-secret-detection", "bandit (Python SAST)"],
    },
]


@router.get("/list", response_model=SkillListResponse)
async def list_skills():
    """List all available CI/CD skills with their descriptions and trigger phrases."""
    return SkillListResponse(skills=_SKILL_CATALOG)


@router.post("/run", response_model=ExecutionResult)
async def run_skill(request: SkillRunRequest):
    """
    Execute a CI/CD skill against a GitHub repository.

    Skills run in dry-run mode by default. The build-and-release skill
    requires dry_run=false to actually create a GitHub release.
    """
    from src.task1_cicd.github_client import FastFailError
    from src.task1_cicd.skill_engine import run_skill as engine_run_skill

    trace_id = generate_trace_id()
    logger.info(
        "skill_run_requested",
        skill=request.skill_name,
        repo=request.repo_url,
        branch=request.branch,
        dry_run=request.dry_run,
        trace_id=trace_id,
    )

    try:
        from src.llm_provider import set_user_keys
        set_user_keys(
            openrouter=request.model.user_openrouter_key,
            nvidia=request.model.user_nvidia_key,
        )
        result = await engine_run_skill(request, trace_id)
        # Skill-name mismatch is a client error — surface as 400 for clear HTTP semantics
        if result.status == ExecutionStatus.FAILED and result.failure_type == FailureType.SKILL_MISMATCH:
            raise HTTPException(status_code=400, detail=result.error or "Unknown skill")
        from src.shared.tracing import trace_url
        result.langsmith_trace_url = trace_url(trace_id)
        return result
    except HTTPException:
        raise
    except FastFailError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("skill_run_unhandled_error", error=str(e), trace_id=trace_id)
        from src.shared.llm_errors import classify_llm_error
        info = classify_llm_error(e)
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.CICD_SKILLS,
            trace_id=trace_id,
            error=f"Internal error: {e}",
            cost_metadata={
                "error_category": info.category,
                "user_message": info.user_message,
                "suggested_action": info.suggested_action,
                "retryable": info.retryable,
            },
        )


@router.post("/stream")
async def stream_run_skill(request: SkillRunRequest):
    """SSE stream of CI/CD skill execution milestones.

    Reviewer-facing events (per skill run):
        stream_start, skill_start, skill_resolved, repo_validated, sha_fetched,
        cache_hit | cache_miss, clone_start, clone_done, language_detected,
        skill_run_start, skill_run_done, summarize_start, summarize_done,
        skill_complete, error, stream_end

    Task 1 runs can take 30-90 s on a fresh clone of a large repo + slow
    OSV.dev / Bandit subprocess. Streaming makes the wait observable.
    """
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from src.shared.llm_errors import classify_llm_error, to_dict
    from src.task1_cicd.github_client import FastFailError
    from src.task1_cicd.skill_engine import run_skill as engine_run_skill

    trace_id = generate_trace_id()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def progress_callback(event: dict) -> None:
        # Non-blocking put: if the consumer disconnected (e.g. user closed
        # the tab), the queue could fill up and the engine would block here
        # forever waiting for a never-arriving consumer drain. Silently
        # drop events when full — losing progress events is strictly
        # better than wedging the engine.
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("sse_queue_full_dropping_event", event=event.get("event"))

    async def run_engine() -> None:
        try:
            from src.llm_provider import set_user_keys
            from src.shared.tracing import trace_url
            set_user_keys(
                openrouter=request.model.user_openrouter_key,
                nvidia=request.model.user_nvidia_key,
            )
            result = await engine_run_skill(request, trace_id, progress_callback=progress_callback)
            # Emit final result as a single SSE event so the FE doesn't have
            # to re-run the skill via /run (was double-executing → 2× latency).
            try:
                result.langsmith_trace_url = trace_url(trace_id)
            except Exception:
                pass
            await queue.put(
                {
                    "event": "result",
                    "trace_id": trace_id,
                    "result": result.model_dump(mode="json"),
                }
            )
        except FastFailError as e:
            await queue.put(
                {
                    "event": "error",
                    "category": "invalid_input",
                    "user_message": str(e),
                    "suggested_action": "Check the request payload (skill_name / repo_url / branch).",
                    "raw_error": str(e),
                    "retryable": False,
                    "trace_id": trace_id,
                }
            )
        except Exception as e:
            err = to_dict(classify_llm_error(e))
            err["trace_id"] = trace_id
            await queue.put({"event": "error", **err})
        finally:
            await queue.put({"event": "stream_end", "trace_id": trace_id})

    runner = asyncio.create_task(run_engine())

    async def event_generator():
        yield f"data: {_json.dumps({'event': 'stream_start', 'trace_id': trace_id})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {_json.dumps(event)}\n\n"
            if event.get("event") == "stream_end":
                break
        if not runner.done():
            runner.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Router endpoints — natural-language query → LLM picks skills → loop
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/auto/run", response_model=ExecutionResult)
async def run_auto_router(request: AutoRouterRequest):
    """Natural-language CI/CD orchestration.

    The user supplies a free-form query (e.g. "are there any leaked API
    keys or vulnerable dependencies?") and the Auto-Router LLM:
      1. plans an ordered set of skills to run,
      2. executes each via the existing skill_engine (with cache hits),
      3. after every skill, decides continue / pivot / stop,
      4. synthesizes a single-paragraph answer tying results back to the query.

    The response.result includes a top-level `skill_executed` list — reviewers
    can use this to confirm the LLM correctly identified e.g. dependency-audit +
    security-scan from a query like "check for vulns and leaked secrets".
    """
    from src.task1_cicd.auto_router import run_auto_router as engine_run_auto

    trace_id = generate_trace_id()
    logger.info(
        "auto_router_requested",
        repo=request.repo_url,
        branch=request.branch,
        query_preview=request.natural_language_query[:120],
        include_hint=request.include_skills_hint,
        exclude_hint=request.exclude_skills_hint,
        dry_run=request.dry_run,
        trace_id=trace_id,
    )

    try:
        from src.llm_provider import set_user_keys
        set_user_keys(
            openrouter=request.model.user_openrouter_key,
            nvidia=request.model.user_nvidia_key,
        )
        result = await engine_run_auto(request, trace_id)
        from src.shared.tracing import trace_url
        result.langsmith_trace_url = trace_url(trace_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("auto_router_unhandled", error=str(e), trace_id=trace_id, exc_info=True)
        from src.shared.llm_errors import classify_llm_error
        info = classify_llm_error(e)
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.CICD_SKILLS,
            trace_id=trace_id,
            error=f"Auto-router error: {e}",
            failure_type=FailureType.LLM_ERROR,
            cost_metadata={
                "error_category": info.category,
                "user_message": info.user_message,
                "suggested_action": info.suggested_action,
                "retryable": info.retryable,
            },
        )


@router.post("/auto/stream")
async def stream_auto_router(request: AutoRouterRequest):
    """SSE stream of auto-router milestones.

    Event sequence:
      stream_start → auto_router_start → plan_done → (per-iteration:
      iteration_start → skill_progress* → iteration_skill_done →
      iteration_decision) → synthesize_start → synthesize_done →
      result → stream_end
    """
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from src.shared.llm_errors import classify_llm_error, to_dict
    from src.task1_cicd.auto_router import run_auto_router as engine_run_auto

    trace_id = generate_trace_id()
    queue: asyncio.Queue = asyncio.Queue(maxsize=400)

    async def progress_callback(event: dict) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("auto_sse_queue_full_dropping", event=event.get("event"))

    async def run_engine() -> None:
        try:
            from src.llm_provider import set_user_keys
            from src.shared.tracing import trace_url
            set_user_keys(
                openrouter=request.model.user_openrouter_key,
                nvidia=request.model.user_nvidia_key,
            )
            result = await engine_run_auto(request, trace_id, progress_callback=progress_callback)
            try:
                result.langsmith_trace_url = trace_url(trace_id)
            except Exception:
                pass
            await queue.put(
                {
                    "event": "result",
                    "trace_id": trace_id,
                    "result": result.model_dump(mode="json"),
                }
            )
        except Exception as e:
            err = to_dict(classify_llm_error(e))
            err["trace_id"] = trace_id
            await queue.put({"event": "error", **err})
        finally:
            await queue.put({"event": "stream_end", "trace_id": trace_id})

    runner = asyncio.create_task(run_engine())

    async def event_generator():
        yield f"data: {_json.dumps({'event': 'stream_start', 'trace_id': trace_id})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {_json.dumps(event)}\n\n"
            if event.get("event") == "stream_end":
                break
        if not runner.done():
            runner.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
