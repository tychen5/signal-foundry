"""
Task 2 Router: Browser Automation Agent API.

Endpoints for submitting natural language browser tasks and retrieving results.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.logger import get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, ModelSelectionRequest, TaskType

router = APIRouter()
logger = get_logger("task2_router")


class BrowserTaskRequest(BaseModel):
    """Request to execute a browser automation task."""

    task_description: str = Field(
        ..., description="Natural language description of the browser task"
    )
    target_url: Optional[str] = Field(
        default=None, description="Starting URL (optional — agent can navigate)"
    )
    max_steps: int = Field(default=15, ge=1, le=50, description="Maximum steps before timeout")
    screenshot: bool = Field(default=True, description="Capture screenshots at each step")
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


class BrowserTaskResponse(BaseModel):
    """Response from browser task execution."""

    trace_id: str
    status: str
    steps: list[dict] = Field(default_factory=list)
    final_result: Optional[str] = None
    screenshots: list[str] = Field(default_factory=list)
    self_corrections: int = 0
    confidence: float = 0.0


@router.post("/execute", response_model=ExecutionResult)
async def execute_browser_task(request: BrowserTaskRequest):
    """
    Execute a browser automation task from natural language description.

    The agent follows a Plan→Execute→Observe→Heal loop:
    1. Planner decomposes the task into steps
    2. Executor runs each step via Playwright
    3. Observer verifies success via AOM/DOM/screenshot
    4. Healer diagnoses and recovers from failures
    """
    from src.shared.logger import generate_trace_id

    trace_id = generate_trace_id()
    logger.info(
        "browser_task_requested",
        task=request.task_description[:100],
        target_url=request.target_url,
        max_steps=request.max_steps,
        trace_id=trace_id,
    )

    # Agent implementation will be connected here
    return ExecutionResult(
        status=ExecutionStatus.SUCCESS,
        task=TaskType.BROWSER_AGENT,
        trace_id=trace_id,
        result={
            "task": request.task_description,
            "target_url": request.target_url,
            "message": "Browser agent executed successfully (skeleton mode)",
            "steps_taken": 0,
            "self_corrections": 0,
        },
    )
