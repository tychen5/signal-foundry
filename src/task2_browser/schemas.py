"""
Browser Automation Agent Schemas.

Pydantic models for the Planner → Executor → Observer → Healer loop.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Types of browser actions the agent can perform."""

    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    SCROLL = "scroll"
    WAIT = "wait"
    EXTRACT = "extract"
    SCREENSHOT = "screenshot"
    KEY_PRESS = "key_press"
    HOVER = "hover"
    DONE = "done"  # Task complete signal


class LocatorStrategy(str, Enum):
    """How an element was located (for self-maintenance tracking)."""

    ACCESSIBILITY = "accessibility"  # Layer 1: role + name from AOM
    SEMANTIC_DOM = "semantic_dom"  # Layer 2: aria-label, data-testid, placeholder
    TEXT_CONTENT = "text_content"  # Layer 2b: visible text match
    CSS_SELECTOR = "css_selector"  # Layer 3: fallback CSS
    COORDINATE = "coordinate"  # Layer 3b: visual coordinate


class FailureRootCause(str, Enum):
    """Root cause classification for failures (used by Healer)."""

    SELECTOR_CHANGED = "selector_changed"
    SELECTOR_AMBIGUOUS = "selector_ambiguous"
    PAGE_NOT_LOADED = "page_not_loaded"
    WRONG_PAGE = "wrong_page"
    ELEMENT_HIDDEN = "element_hidden"
    ELEMENT_NOT_FOUND = "element_not_found"
    NETWORK_ERROR = "network_error"
    CAPTCHA_DETECTED = "captcha_detected"
    UNEXPECTED_POPUP = "unexpected_popup"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class BrowserAction(BaseModel):
    """A single action for the browser executor to perform."""

    action_type: ActionType
    target_description: str = Field(
        default="", description="Semantic description of target element (e.g., 'search input box')"
    )
    value: str = Field(default="", description="Value to fill/type, URL to navigate to, etc.")
    selector: str = Field(default="", description="CSS/XPath selector (fallback)")
    reasoning: str = Field(default="", description="LLM's reasoning for this action")
    success_criteria: str = Field(default="", description="What should change after this action succeeds")


class PageState(BaseModel):
    """Captured state of the browser page after an observation."""

    url: str = ""
    title: str = ""
    accessibility_tree: str = Field(default="", description="Simplified accessibility tree snapshot")
    visible_text_summary: str = Field(default="", description="Key visible text on the page (truncated)")
    has_input_fields: bool = False
    has_buttons: bool = False
    has_links: bool = False
    error_indicators: list[str] = Field(default_factory=list, description="Error messages, toasts, alerts detected")
    screenshot_path: str = Field(default="", description="Path to screenshot file")


class VerificationResult(BaseModel):
    """Result of post-action verification (silent failure prevention)."""

    success: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    state_changed: bool = False
    url_changed: bool = False
    dom_changed: bool = False


class StepResult(BaseModel):
    """Result of a single step in the agent loop."""

    step_number: int
    action: BrowserAction
    before_state: Optional[PageState] = None
    after_state: Optional[PageState] = None
    verification: Optional[VerificationResult] = None
    locator_strategy_used: Optional[LocatorStrategy] = None
    error: Optional[str] = None
    healer_activated: bool = False
    healer_diagnosis: Optional[str] = None
    healer_recovery: Optional[str] = None
    duration_ms: float = 0.0


class TaskPlan(BaseModel):
    """Decomposed task plan from the Planner."""

    original_task: str
    steps: list[BrowserAction] = Field(default_factory=list)
    predicted_failure_points: list[str] = Field(default_factory=list)
    requires_login: bool = False
    estimated_complexity: str = "medium"  # easy, medium, hard


class Diagnosis(BaseModel):
    """Failure diagnosis from the Healer."""

    root_cause: FailureRootCause
    explanation: str = ""
    recovery_strategy: str = ""
    alternative_action: Optional[BrowserAction] = None
    should_retry: bool = True
    confidence: float = 0.5


class AgentResult(BaseModel):
    """Complete result from a browser agent execution."""

    trace_id: str = ""
    task_description: str = ""
    target_url: str = ""
    # success | partial | failed | not_found | unverified
    # not_found  → agent ran cleanly but the target data does not exist
    # unverified → final answer's numbers can't be sourced from observed text
    status: str = "success"
    steps: list[StepResult] = Field(default_factory=list)
    final_answer: str = Field(default="", description="Extracted data or task completion summary")
    total_steps: int = 0
    self_corrections: int = 0
    healer_activations: int = 0
    total_duration_ms: float = 0.0
    cost_usd: float = 0.0
    llm_calls: int = 0
    failure_modes: list[str] = Field(default_factory=list, description="Encountered failure types")
    screenshots: list[str] = Field(default_factory=list, description="Paths to step screenshots")
    metadata: dict[str, Any] = Field(default_factory=dict)
