"""
Task 2 Router: Browser Automation Agent API.

Endpoints for submitting natural language browser tasks and retrieving results.
Wired to the full Planner → Executor → Observer → Healer agent loop.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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

    try:
        from src.task2_browser.agent import BrowserAgent

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
        )

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS
            if result.status == "success"
            else ExecutionStatus.PARTIAL
            if result.status == "partial"
            else ExecutionStatus.FAILED,
            task=TaskType.BROWSER_AGENT,
            trace_id=trace_id,
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

    except Exception as e:
        logger.error("browser_task_failed", error=str(e), trace_id=trace_id)
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.BROWSER_AGENT,
            trace_id=trace_id,
            error=str(e),
            failure_type=FailureType.TOOL_ERROR,
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
