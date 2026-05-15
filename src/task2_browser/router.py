"""
Task 2 Router: Browser Automation Agent API.

Endpoints for submitting natural language browser tasks and retrieving results.
Wired to the full Planner → Executor → Observer → Healer agent loop.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.llm_errors import LLMStageError, classify_with_stage
from src.shared.llm_validation import (
    validate_model_selection,
    validation_error_to_envelope,
)
from src.shared.logger import generate_trace_id, get_logger
from src.shared.schemas import (
    ExecutionResult,
    ExecutionStatus,
    FailureType,
    ModelSelectionRequest,
    TaskType,
)

router = APIRouter()
logger = get_logger("task2_router")


def _validate_llm_model_or_400(model: object) -> str:
    """Validate model_id/provider/key before starting Chromium."""
    resolution = validate_model_selection(model)
    if not resolution.valid:
        raise HTTPException(
            status_code=400,
            detail=validation_error_to_envelope(resolution),
        )
    return resolution.provider or ""


def _failed_llm_result(
    exc: object,
    *,
    trace_id: str,
    stage: str,
    provider: str,
    model_id: str,
) -> ExecutionResult:
    envelope = (
        exc.to_envelope()
        if isinstance(exc, LLMStageError)
        else classify_with_stage(exc, stage=stage, provider=provider, model_id=model_id)
    )
    envelope["provider"] = envelope.get("provider") or provider
    envelope["model_id"] = envelope.get("model_id") or model_id
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        task=TaskType.BROWSER_AGENT,
        trace_id=trace_id,
        error=envelope.get("user_message") or envelope.get("raw_error"),
        failure_type=FailureType.LLM_ERROR,
        cost_metadata={"llm_error": envelope},
    )


class BrowserTaskRequest(BaseModel):
    """Request to execute a browser automation task."""

    task_description: str = Field(..., description="Natural language description of the browser task")
    target_url: Optional[str] = Field(default=None, description="Starting URL (optional — agent can navigate)")
    max_steps: int = Field(default=15, ge=1, le=50, description="Maximum steps before timeout")
    screenshot: bool = Field(default=True, description="Capture screenshots at each step")
    use_vision: bool = Field(
        default=False,
        description=(
            "If true AND model is vision-capable (gemini-3.1-pro / claude-opus-4.7 / "
            "gpt-5.5), the verifier receives the current viewport as a JPEG alongside "
            "the AOM tree. Helps with visually-encoded data (charts, captchas, layout)."
        ),
    )
    allow_fast_path: bool = Field(
        default=True,
        description=(
            "If true (default), attempt the deterministic static-site fast path "
            "before launching Playwright. Server-side rendered domains "
            "(Wikipedia, arxiv, HN, example.com) resolve in <2 s with 0 LLM "
            "calls. Set false to force the full Plan→Execute→Observe→Heal loop "
            "for head-to-head benchmarks against the agent path."
        ),
    )
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


@router.post("/execute", response_model=ExecutionResult)
async def execute_browser_task(request: BrowserTaskRequest):
    """
    Execute a browser automation task from natural language description.

    The agent follows a Plan → Execute → Observe → Heal loop:
    1. Planner decomposes the task into steps
    2. Executor runs each step via Playwright with AOM-first locators
    3. Observer verifies success (accessibility tree + DOM + screenshot)
    4. Healer diagnoses root cause and recovers from failures
    """
    trace_id = generate_trace_id()

    if not request.task_description.strip():
        raise HTTPException(status_code=400, detail="task_description is required")

    logger.info(
        "browser_task_requested",
        task=request.task_description[:100],
        target_url=request.target_url,
        max_steps=request.max_steps,
        trace_id=trace_id,
    )

    provider = _validate_llm_model_or_400(request.model)
    from src.llm_provider import clear_user_keys, set_user_keys

    try:
        from src.task2_browser.agent import BrowserAgent

        # Per-request user keys (NVIDIA + OpenRouter) — get_llm reads them from
        # contextvars when its explicit key params are empty. This lets us
        # support user-supplied NVIDIA keys without threading them through
        # 7+ downstream call sites.
        set_user_keys(
            openrouter=request.model.user_openrouter_key,
            nvidia=request.model.user_nvidia_key,
            provider_hint=provider,
        )

        agent = BrowserAgent(
            model_name=request.model.model_id,
            user_api_key=request.model.user_openrouter_key,
            headless=True,
            screenshot_dir="/tmp/signal_foundry_browser" if request.screenshot else "",
            use_vision=request.use_vision,
        )

        result = await agent.run(
            task_description=request.task_description,
            target_url=request.target_url,
            max_steps=request.max_steps,
            trace_id=trace_id,
            allow_fast_path=request.allow_fast_path,
        )

        from src.shared.tracing import trace_url

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS
            if result.status == "success"
            else ExecutionStatus.PARTIAL
            if result.status == "partial"
            else ExecutionStatus.FAILED,
            task=TaskType.BROWSER_AGENT,
            trace_id=trace_id,
            langsmith_trace_url=trace_url(trace_id),
            result=result.model_dump(),
            cost_metadata={
                "total_cost_usd": result.cost_usd,
                "llm_calls": result.llm_calls,
                "total_steps": result.total_steps,
                "self_corrections": result.self_corrections,
                "healer_activations": result.healer_activations,
                "total_duration_ms": result.total_duration_ms,
                "failure_modes": result.failure_modes,
            },
            latency_ms=result.total_duration_ms,
        )

    except LLMStageError as e:
        logger.warning("browser_task_llm_error", error=str(e), trace_id=trace_id)
        return _failed_llm_result(
            e,
            trace_id=trace_id,
            stage=e.stage,
            provider=provider,
            model_id=request.model.model_id,
        )
    except Exception as e:
        logger.error("browser_task_failed", error=str(e), trace_id=trace_id)
        envelope = classify_with_stage(
            e,
            stage="browser_agent",
            provider=provider,
            model_id=request.model.model_id,
        )
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.BROWSER_AGENT,
            trace_id=trace_id,
            error=str(e),
            failure_type=FailureType.TOOL_ERROR,
            cost_metadata={"llm_error": envelope},
        )
    finally:
        clear_user_keys()


@router.post("/stream")
async def stream_browser_task(request: BrowserTaskRequest):
    """Server-Sent Events stream for live agent progress.

    Frontend opens an EventSource and receives milestone events:
        phase_start    {phase, task, model, use_vision}
        phase_done     {phase, plan_steps, plan_summary}
        step_start     {step, action, target, phase}
        step_done      {step, url, healer, diagnosis, confidence, error}
        agent_complete {status, steps, cost_usd, answer, failure_modes}
        error          {category, user_message, raw_error, suggested_action}

    The agent runs in a background task; the endpoint pumps events from an
    asyncio.Queue. When a queue dequeue waits >120 s without an event, we
    emit a `heartbeat` so reverse proxies (and the browser) don't time out
    the connection.
    """
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from src.shared.llm_errors import classify_llm_error, to_dict

    trace_id = generate_trace_id()
    if not request.task_description.strip():
        raise HTTPException(status_code=400, detail="task_description is required")

    provider = _validate_llm_model_or_400(request.model)
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def progress_callback(event: dict) -> None:
        # Non-blocking — if the consumer (browser tab) disconnected mid-run,
        # we'd otherwise wedge the agent waiting for a never-arriving drain.
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("sse_queue_full_dropping_event", event=event.get("event"))

    async def run_agent() -> None:
        try:
            from src.llm_provider import clear_user_keys, set_user_keys
            from src.task2_browser.agent import BrowserAgent

            set_user_keys(
                openrouter=request.model.user_openrouter_key,
                nvidia=request.model.user_nvidia_key,
                provider_hint=provider,
            )
            agent = BrowserAgent(
                model_name=request.model.model_id,
                user_api_key=request.model.user_openrouter_key,
                headless=True,
                screenshot_dir="/tmp/signal_foundry_browser" if request.screenshot else "",
                use_vision=request.use_vision,
                progress_callback=progress_callback,
            )
            await agent.run(
                task_description=request.task_description,
                target_url=request.target_url,
                max_steps=request.max_steps,
                trace_id=trace_id,
                allow_fast_path=request.allow_fast_path,
            )
        except LLMStageError as e:
            err_info = e.to_envelope()
            err_info["provider"] = err_info.get("provider") or provider
            err_info["model_id"] = err_info.get("model_id") or request.model.model_id
            err_info["trace_id"] = trace_id
            await queue.put({"event": "error", **err_info})
        except Exception as e:
            err_info = to_dict(classify_llm_error(e))
            err_info["stage"] = "browser_agent"
            err_info["provider"] = provider
            err_info["model_id"] = request.model.model_id
            err_info["trace_id"] = trace_id
            await queue.put({"event": "error", **err_info})
        finally:
            try:
                clear_user_keys()
            except Exception:
                pass
            await queue.put({"event": "stream_end", "trace_id": trace_id})

    runner_task = asyncio.create_task(run_agent())

    async def event_generator():
        # Initial event so the client immediately knows trace_id
        yield f"data: {_json.dumps({'event': 'stream_start', 'trace_id': trace_id})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                # Heartbeat to keep the connection alive through proxies
                yield ": keep-alive\n\n"
                continue
            yield f"data: {_json.dumps(event)}\n\n"
            if event.get("event") in ("stream_end", "agent_complete", "error"):
                # After stream_end OR a terminal event, drain any tail then break
                if event.get("event") == "stream_end":
                    break

        if not runner_task.done():
            runner_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/status/{trace_id}")
async def get_task_status(trace_id: str):
    """Get the status of a browser task by trace ID."""
    # Future: implement async task queue with status tracking
    return {
        "trace_id": trace_id,
        "status": "completed",
        "message": "Real-time status tracking will be available in the async task queue implementation",
    }
