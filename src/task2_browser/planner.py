"""
Planner: LLM-powered task decomposition and step-by-step action planning.

Takes a natural language task description and produces an ordered sequence
of BrowserActions, with predicted failure points for proactive healing.

Uses versioned prompts from prompts/browser_agent/.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm_provider import get_llm
from src.shared.cost_tracker import get_cost_tracker
from src.shared.llm_utils import coerce_message_text
from src.shared.logger import get_logger
from src.task2_browser.schemas import (
    ActionType,
    BrowserAction,
    PageState,
    TaskPlan,
)

logger = get_logger("planner")
cost_tracker = get_cost_tracker()


def _resp_text(response) -> str:
    """Pull plain text out of a chat response, regardless of provider shape."""
    return coerce_message_text(getattr(response, "content", response))

_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "prompts",
    "browser_agent",
)


def _load_prompt(filename: str) -> str:
    """Load a prompt from the versioned prompts directory."""
    filepath = os.path.join(_PROMPTS_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning("prompt_file_not_found", file=filename)
        return ""


def _load_prompt_versioned(stem: str) -> str:
    """Load latest prompt version (v3 -> v2 -> v1 fallback)."""
    for version in ("v3", "v2", "v1"):
        text = _load_prompt(f"{version}_{stem}.txt")
        if text:
            return text
    return ""


# v3 actor/verifier prompts add multi-screenshot vision instructions.
# Falls back to v2/v1 if newer prompts are absent.
PLANNER_PROMPT = _load_prompt_versioned("planner")
ACTOR_PROMPT = _load_prompt_versioned("actor")
VERIFIER_PROMPT = _load_prompt_versioned("verifier")


async def plan_task(
    task_description: str,
    target_url: Optional[str] = None,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    trace_id: str = "",
) -> TaskPlan:
    """
    Decompose a natural language task into browser action steps.

    Args:
        task_description: What the user wants the browser agent to do
        target_url: Starting URL (optional)
        model_name: LLM model to use
        user_api_key: User's API key
        trace_id: Request trace ID

    Returns:
        TaskPlan with ordered steps
    """
    llm = get_llm(
        model_name=model_name,
        user_openrouter_key=user_api_key,
        temperature=0.0,
        max_tokens=2000,
    )

    context = f"Task: {task_description}\n"
    if target_url:
        context += f"Starting URL: {target_url}\n"

    try:
        _t0 = time.time()
        response = await llm.ainvoke(
            [
                SystemMessage(content=PLANNER_PROMPT),
                HumanMessage(content=context),
            ]
        )

        cost_tracker.record_call(
            model=model_name or "default",
            tokens_in=len(PLANNER_PROMPT + context) // 4,
            tokens_out=len(_resp_text(response)) // 4,
            latency_ms=round((time.time() - _t0) * 1000, 1),
            task="task2_browser",
            operation="plan",
            trace_id=trace_id,
        )

        return _parse_plan(_resp_text(response), task_description, target_url)

    except Exception as e:
        logger.warning("planning_failed", error=str(e))
        # Fallback: generate a basic plan
        return _create_fallback_plan(task_description, target_url)


async def decide_next_action(
    task_description: str,
    page_state: PageState,
    completed_steps: list[str],
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    trace_id: str = "",
    screenshot_b64: Optional[str] = None,
    screenshot_history: Optional[list[tuple[str, str]]] = None,
) -> BrowserAction:
    """
    Decide the next action given the current page state (reactive planning).

    This is used in the main loop — the agent observes the page and decides
    what to do next, rather than blindly following a pre-made plan.

    Args:
        task_description: Original task
        page_state: Current page state from Observer
        completed_steps: Summary of steps already taken
        model_name: LLM model
        user_api_key: User's API key
        trace_id: Trace ID
        screenshot_b64: optional base64-encoded JPEG of current viewport.
            When provided AND model is vision-capable, the actor sees the
            rendered page so it can pick targets that AOM can't expose
            (chart areas, image-only buttons, visual-only data).

    Returns:
        Next BrowserAction to execute
    """
    from src.task2_browser.vision import (
        is_vision_capable,
        make_multimodal_message,
        make_multimodal_message_history,
    )

    llm = get_llm(
        model_name=model_name,
        user_openrouter_key=user_api_key,
        temperature=0.0,
        max_tokens=800,
    )

    steps_summary = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(completed_steps[-5:]))

    context = (
        f"TASK: {task_description}\n\n"
        f"CURRENT PAGE:\n"
        f"  URL: {page_state.url}\n"
        f"  Title: {page_state.title}\n\n"
        f"ACCESSIBILITY TREE:\n{page_state.accessibility_tree[:2500]}\n\n"
        f"VISIBLE TEXT (excerpt):\n{page_state.visible_text_summary[:800]}\n\n"
        f"STEPS ALREADY TAKEN:\n{steps_summary}\n\n"
        f"ERROR INDICATORS: {page_state.error_indicators}\n"
    )

    vision_capable = is_vision_capable(model_name)
    if screenshot_history and vision_capable:
        # Multi-snapshot path — show LLM the sequence of states so it can see
        # what changed since the last action (click that did nothing, modal
        # that popped up, error toast that appeared)
        user_msg = make_multimodal_message_history(context, screenshot_history)
    elif screenshot_b64 and vision_capable:
        user_msg = make_multimodal_message(context, screenshot_b64)
    else:
        user_msg = HumanMessage(content=context)

    try:
        _t0 = time.time()
        response = await llm.ainvoke(
            [
                SystemMessage(content=ACTOR_PROMPT),
                user_msg,
            ]
        )

        cost_tracker.record_call(
            model=model_name or "default",
            tokens_in=len(ACTOR_PROMPT + context) // 4,
            tokens_out=len(_resp_text(response)) // 4,
            latency_ms=round((time.time() - _t0) * 1000, 1),
            task="task2_browser",
            operation="decide_action",
            trace_id=trace_id,
        )

        return _parse_action(_resp_text(response))

    except Exception as e:
        logger.warning("action_decision_failed", error=str(e))
        return BrowserAction(
            action_type=ActionType.DONE,
            reasoning=f"Decision failed: {str(e)}",
        )


async def verify_with_llm(
    task_description: str,
    page_state: PageState,
    completed_steps: list[str],
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    trace_id: str = "",
    screenshot_b64: Optional[str] = None,
    screenshot_history: Optional[list[tuple[str, str]]] = None,
) -> tuple[bool, str, float]:
    """
    LLM-based verification: has the task been completed?

    Args:
        screenshot_b64: optional base64-encoded JPEG of CURRENT viewport.
        screenshot_history: optional list of (label, base64) for the last
            N viewports. When provided + vision-capable model, the verifier
            sees the full sequence — useful to confirm an action's effect
            (was the modal dismissed? did the search complete?).

    Returns:
        Tuple of (is_complete, final_answer, confidence)
    """
    if not VERIFIER_PROMPT:
        return False, "", 0.5

    from src.task2_browser.vision import (
        is_vision_capable,
        make_multimodal_message,
        make_multimodal_message_history,
    )

    llm = get_llm(
        model_name=model_name,
        user_openrouter_key=user_api_key,
        temperature=0.0,
        max_tokens=500,
    )

    steps_summary = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(completed_steps))

    context = (
        f"TASK: {task_description}\n\n"
        f"CURRENT PAGE URL: {page_state.url}\n"
        f"CURRENT PAGE TITLE: {page_state.title}\n\n"
        f"VISIBLE TEXT:\n{page_state.visible_text_summary[:1500]}\n\n"
        f"STEPS TAKEN:\n{steps_summary}\n"
    )

    # Vision: prefer multi-snapshot history when available, fall back to
    # single screenshot, then text-only. Silent degradation across the
    # full model registry.
    vision_capable = is_vision_capable(model_name)
    if screenshot_history and vision_capable:
        user_msg = make_multimodal_message_history(context, screenshot_history)
    elif screenshot_b64 and vision_capable:
        user_msg = make_multimodal_message(context, screenshot_b64)
    else:
        user_msg = HumanMessage(content=context)

    try:
        _t0 = time.time()
        response = await llm.ainvoke(
            [
                SystemMessage(content=VERIFIER_PROMPT),
                user_msg,
            ]
        )

        cost_tracker.record_call(
            model=model_name or "default",
            tokens_in=len(VERIFIER_PROMPT + context) // 4,
            tokens_out=len(_resp_text(response)) // 4,
            latency_ms=round((time.time() - _t0) * 1000, 1),
            task="task2_browser",
            operation="verify",
            trace_id=trace_id,
        )

        return _parse_verification(_resp_text(response))

    except Exception as e:
        logger.warning("verification_failed", error=str(e))
        return False, "", 0.3


def _parse_plan(llm_response: str, task: str, target_url: Optional[str]) -> TaskPlan:
    """Parse LLM plan response into TaskPlan model."""
    steps: list[BrowserAction] = []

    # Try JSON parsing first
    try:
        json_match = re.search(r"\[.*\]", llm_response, re.DOTALL)
        if json_match:
            raw_steps = json.loads(json_match.group())
            for raw in raw_steps:
                action_type = _map_action_type(raw.get("action", raw.get("action_type", "click")))
                steps.append(
                    BrowserAction(
                        action_type=action_type,
                        target_description=raw.get("target", raw.get("target_description", "")),
                        value=raw.get("value", ""),
                        reasoning=raw.get("reasoning", ""),
                        success_criteria=raw.get("success_criteria", ""),
                    )
                )
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: parse numbered steps
    if not steps:
        lines = llm_response.strip().split("\n")
        for line in lines:
            line = line.strip()
            if re.match(r"^\d+[\.\)]\s", line):
                steps.append(
                    BrowserAction(
                        action_type=ActionType.CLICK,
                        target_description=line[3:].strip(),
                        reasoning="From planner step list",
                    )
                )

    # If still no steps, create fallback
    if not steps:
        return _create_fallback_plan(task, target_url)

    # Prepend navigation step if URL provided
    if target_url and (not steps or steps[0].action_type != ActionType.NAVIGATE):
        steps.insert(
            0,
            BrowserAction(
                action_type=ActionType.NAVIGATE,
                target_description=f"Navigate to {target_url}",
                value=target_url,
                reasoning="Navigate to starting URL",
                success_criteria="Page loads successfully",
            ),
        )

    return TaskPlan(
        original_task=task,
        steps=steps,
        estimated_complexity="medium",
    )


def _create_fallback_plan(task: str, target_url: Optional[str]) -> TaskPlan:
    """Create a basic fallback plan when LLM planning fails."""
    steps: list[BrowserAction] = []

    if target_url:
        steps.append(
            BrowserAction(
                action_type=ActionType.NAVIGATE,
                target_description=f"Navigate to {target_url}",
                value=target_url,
                reasoning="Navigate to starting URL",
            )
        )

    # The reactive actor loop will handle the rest
    return TaskPlan(
        original_task=task,
        steps=steps,
        estimated_complexity="unknown",
    )


def _parse_action(llm_response: str) -> BrowserAction:
    """Parse LLM actor response into a single BrowserAction."""
    # Try JSON first
    try:
        json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
        if json_match:
            raw = json.loads(json_match.group())
            action_type = _map_action_type(raw.get("action", raw.get("action_type", "done")))
            return BrowserAction(
                action_type=action_type,
                target_description=raw.get("target", raw.get("target_description", "")),
                value=raw.get("value", ""),
                selector=raw.get("selector", ""),
                reasoning=raw.get("reasoning", ""),
                success_criteria=raw.get("success_criteria", ""),
            )
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: if response mentions "done" or "complete"
    response_lower = llm_response.lower()
    if "done" in response_lower or "task complete" in response_lower or "finished" in response_lower:
        answer = llm_response.strip()
        return BrowserAction(
            action_type=ActionType.DONE,
            value=answer,
            reasoning="Task appears complete based on LLM response",
        )

    return BrowserAction(
        action_type=ActionType.DONE,
        reasoning=f"Could not parse action from LLM response: {llm_response[:100]}",
    )


def _parse_verification(llm_response: str) -> tuple[bool, str, float]:
    """Parse LLM verification response."""
    response_lower = llm_response.lower()

    # Try JSON
    try:
        json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
        if json_match:
            raw = json.loads(json_match.group())
            return (
                raw.get("complete", False),
                raw.get("answer", raw.get("final_answer", "")),
                raw.get("confidence", 0.5),
            )
    except (json.JSONDecodeError, TypeError):
        pass

    # Check for negation first
    has_negation = any(neg in response_lower[:80] for neg in ["not complete", "not yet", "no,", "no "])
    has_positive = "yes" in response_lower[:50] or ("complete" in response_lower[:80] and not has_negation)
    is_complete = has_positive and not has_negation
    confidence = 0.8 if is_complete else 0.3
    return is_complete, llm_response.strip(), confidence


def _map_action_type(action_str: str) -> ActionType:
    """Map string action names to ActionType enum."""
    mapping = {
        "navigate": ActionType.NAVIGATE,
        "goto": ActionType.NAVIGATE,
        "go_to": ActionType.NAVIGATE,
        "click": ActionType.CLICK,
        "fill": ActionType.FILL,
        "type": ActionType.FILL,
        "input": ActionType.FILL,
        "select": ActionType.SELECT,
        "choose": ActionType.SELECT,
        "scroll": ActionType.SCROLL,
        "wait": ActionType.WAIT,
        "extract": ActionType.EXTRACT,
        "read": ActionType.EXTRACT,
        "screenshot": ActionType.SCREENSHOT,
        "key_press": ActionType.KEY_PRESS,
        "press": ActionType.KEY_PRESS,
        "enter": ActionType.KEY_PRESS,
        "hover": ActionType.HOVER,
        "done": ActionType.DONE,
        "complete": ActionType.DONE,
        "finish": ActionType.DONE,
    }
    return mapping.get(action_str.lower(), ActionType.CLICK)
