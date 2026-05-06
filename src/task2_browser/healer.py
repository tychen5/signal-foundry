"""
Healer: Self-healing failure diagnosis and recovery.

NOT just try/except retry — diagnoses the root cause and selects
a targeted recovery strategy based on page state analysis.

Root cause taxonomy:
- selector_changed: UI element moved/renamed but still exists
- page_not_loaded: page is blank or still loading
- wrong_page: navigated to unexpected page
- element_hidden: element exists but is behind overlay/popup
- element_not_found: target does not exist on current page
- network_error: connection/timeout failure
- captcha_detected: CAPTCHA or anti-bot challenge
- unexpected_popup: dialog/modal blocking interaction
"""

from __future__ import annotations

import os
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
    Diagnosis,
    FailureRootCause,
    PageState,
)

logger = get_logger("healer")
cost_tracker = get_cost_tracker()

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
    """Load latest prompt version (v2 preferred, v1 fallback)."""
    for version in ("v2", "v1"):
        text = _load_prompt(f"{version}_{stem}.txt")
        if text:
            return text
    return ""


# v2 healer adds rate_limit_429 / login_wall / paywall / frame_detached classes.
HEALER_PROMPT = _load_prompt_versioned("healer")


def diagnose_deterministic(
    error_message: str,
    page_state: PageState,
    action: BrowserAction,
) -> Diagnosis:
    """
    Fast deterministic diagnosis without LLM (for common failure patterns).

    Falls back to LLM diagnosis for ambiguous cases.
    """
    error_lower = (error_message or "").lower()

    # Anti-bot / rate-limit responses. These MUST be diagnosed before generic
    # network errors because the underlying error string may also contain
    # "net::" / "err_" depending on the Playwright version.
    if any(s in error_lower for s in ("429", "too many requests", "rate limit", "ratelimit")):
        return Diagnosis(
            root_cause=FailureRootCause.NETWORK_ERROR,
            explanation="Server returned rate-limit (429). Anti-bot or quota exhaustion.",
            recovery_strategy="Back off (5–15s), then retry once. Repeated 429s should fail the task rather than burn budget.",
            should_retry=True,
            confidence=0.95,
        )
    if any(s in error_lower for s in ("403", "forbidden", "access denied", "blocked")):
        return Diagnosis(
            root_cause=FailureRootCause.CAPTCHA_DETECTED,
            explanation="403/Forbidden. Likely anti-bot block, geofence, or missing auth.",
            recovery_strategy="Cannot bypass automatically. Report as blocked rather than loop on retries.",
            should_retry=False,
            confidence=0.9,
        )
    if "ssl" in error_lower or "cert" in error_lower or "ssl_error" in error_lower:
        return Diagnosis(
            root_cause=FailureRootCause.NETWORK_ERROR,
            explanation=f"TLS/cert error: {error_message[:120]}",
            recovery_strategy="Cannot fix from agent. Verify URL spelling or report as blocked.",
            should_retry=False,
            confidence=0.95,
        )
    # Playwright sometimes fails because the underlying frame/page got
    # navigated/destroyed mid-action (common during heavy SPA redirects).
    if any(s in error_lower for s in ("frame was detached", "target closed", "execution context was destroyed")):
        return Diagnosis(
            root_cause=FailureRootCause.PAGE_NOT_LOADED,
            explanation="Page or frame navigated/destroyed mid-action.",
            recovery_strategy="Re-observe page state, then retry the action against the new DOM.",
            should_retry=True,
            confidence=0.85,
        )

    # Timeout / not found patterns
    if "timeout" in error_lower:
        if "waiting for" in error_lower or "locator" in error_lower:
            return Diagnosis(
                root_cause=FailureRootCause.ELEMENT_NOT_FOUND,
                explanation=f"Element not found within timeout: {action.target_description}",
                recovery_strategy="Try alternative locator: use visible text, aria-label, or broader CSS selector",
                should_retry=True,
                confidence=0.8,
            )
        return Diagnosis(
            root_cause=FailureRootCause.TIMEOUT,
            explanation="Operation timed out",
            recovery_strategy="Wait longer and retry, or check network connectivity",
            should_retry=True,
            confidence=0.7,
        )

    # Navigation errors
    if "net::" in error_lower or "err_" in error_lower:
        return Diagnosis(
            root_cause=FailureRootCause.NETWORK_ERROR,
            explanation=f"Network error: {error_message[:100]}",
            recovery_strategy="Check URL and retry navigation",
            should_retry=True,
            confidence=0.9,
        )

    # Element interaction failures
    if "not visible" in error_lower or "not interactable" in error_lower or "hidden" in error_lower:
        # Check if there might be a popup
        if page_state.error_indicators or "cookie" in page_state.visible_text_summary.lower():
            return Diagnosis(
                root_cause=FailureRootCause.UNEXPECTED_POPUP,
                explanation="Element may be behind a popup or overlay",
                recovery_strategy="Dismiss popup/cookie banner first, then retry",
                should_retry=True,
                confidence=0.7,
            )
        return Diagnosis(
            root_cause=FailureRootCause.ELEMENT_HIDDEN,
            explanation="Element exists but is not visible/interactable",
            recovery_strategy="Scroll to element, wait for visibility, or dismiss overlay",
            should_retry=True,
            confidence=0.7,
        )

    # CAPTCHA detection
    if "captcha" in error_lower or "captcha" in page_state.visible_text_summary.lower():
        return Diagnosis(
            root_cause=FailureRootCause.CAPTCHA_DETECTED,
            explanation="CAPTCHA or anti-bot challenge detected",
            recovery_strategy="Cannot solve CAPTCHA automatically. Report as blocked.",
            should_retry=False,
            confidence=0.9,
        )

    # Page not loaded
    if not page_state.url or page_state.url == "about:blank":
        return Diagnosis(
            root_cause=FailureRootCause.PAGE_NOT_LOADED,
            explanation="Page has not loaded or is blank",
            recovery_strategy="Wait for page load and retry",
            should_retry=True,
            confidence=0.8,
        )

    # Wrong page (URL doesn't match expected)
    if "not found" in error_lower and page_state.url:
        return Diagnosis(
            root_cause=FailureRootCause.ELEMENT_NOT_FOUND,
            explanation=f"Target element not found on current page ({page_state.url})",
            recovery_strategy="Re-examine page structure and try different element description",
            should_retry=True,
            confidence=0.6,
        )

    # Default — ambiguous
    return Diagnosis(
        root_cause=FailureRootCause.UNKNOWN,
        explanation=f"Unclassified error: {error_message[:200]}",
        recovery_strategy="Try alternative approach",
        should_retry=True,
        confidence=0.3,
    )


async def diagnose_with_llm(
    error_message: str,
    page_state: PageState,
    action: BrowserAction,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    trace_id: str = "",
) -> Diagnosis:
    """
    LLM-powered diagnosis for ambiguous failures.

    Sends the error, page state, and action context to the LLM
    for deeper root cause analysis and recovery suggestion.
    """
    if not HEALER_PROMPT:
        return diagnose_deterministic(error_message, page_state, action)

    try:
        llm = get_llm(
            model_name=model_name or "deepseek-ai/deepseek-v4-pro",
            user_openrouter_key=user_api_key,
            temperature=0.0,
            max_tokens=500,
        )

        context = (
            f"Error: {error_message}\n\n"
            f"Action attempted: {action.action_type.value} on '{action.target_description}'\n"
            f"Value: {action.value}\n\n"
            f"Page URL: {page_state.url}\n"
            f"Page title: {page_state.title}\n\n"
            f"Accessibility tree (excerpt):\n{page_state.accessibility_tree[:1500]}\n\n"
            f"Error indicators on page: {page_state.error_indicators}\n"
        )

        _t0 = time.time()
        response = await llm.ainvoke(
            [
                SystemMessage(content=HEALER_PROMPT),
                HumanMessage(content=context),
            ]
        )

        text = coerce_message_text(getattr(response, "content", response))
        cost_tracker.record_call(
            model=model_name or "deepseek-ai/deepseek-v4-pro",
            tokens_in=len(context) // 4,
            tokens_out=len(text) // 4,
            latency_ms=round((time.time() - _t0) * 1000, 1),
            task="task2_browser",
            operation="heal",
            trace_id=trace_id,
        )

        # Parse LLM response into Diagnosis
        return _parse_llm_diagnosis(text, error_message, action)

    except Exception as e:
        logger.warning("llm_diagnosis_failed", error=str(e))
        return diagnose_deterministic(error_message, page_state, action)


def _parse_llm_diagnosis(llm_response: str, error_message: str, action: BrowserAction) -> Diagnosis:
    """Parse LLM diagnosis response into a Diagnosis model."""
    response_lower = llm_response.lower()

    # Map keywords to root causes
    cause_map = {
        "selector": FailureRootCause.SELECTOR_CHANGED,
        "not loaded": FailureRootCause.PAGE_NOT_LOADED,
        "wrong page": FailureRootCause.WRONG_PAGE,
        "hidden": FailureRootCause.ELEMENT_HIDDEN,
        "not found": FailureRootCause.ELEMENT_NOT_FOUND,
        "network": FailureRootCause.NETWORK_ERROR,
        "captcha": FailureRootCause.CAPTCHA_DETECTED,
        "popup": FailureRootCause.UNEXPECTED_POPUP,
        "overlay": FailureRootCause.UNEXPECTED_POPUP,
        "timeout": FailureRootCause.TIMEOUT,
    }

    root_cause = FailureRootCause.UNKNOWN
    for keyword, cause in cause_map.items():
        if keyword in response_lower:
            root_cause = cause
            break

    return Diagnosis(
        root_cause=root_cause,
        explanation=llm_response[:300],
        recovery_strategy=llm_response[300:600] if len(llm_response) > 300 else "Try alternative approach",
        should_retry=root_cause != FailureRootCause.CAPTCHA_DETECTED,
        confidence=0.6,
    )


def suggest_alternative_action(
    diagnosis: Diagnosis,
    original_action: BrowserAction,
    page_state: PageState,
) -> Optional[BrowserAction]:
    """
    Suggest an alternative action based on the diagnosis.

    This is the substantive self-correction — not just retrying the same action.
    """
    cause = diagnosis.root_cause

    if cause == FailureRootCause.UNEXPECTED_POPUP:
        return BrowserAction(
            action_type=ActionType.CLICK,
            target_description="close button or dismiss popup",
            value="",
            reasoning="Dismiss popup/overlay before retrying original action",
            success_criteria="Popup should disappear",
        )

    if cause == FailureRootCause.ELEMENT_HIDDEN:
        return BrowserAction(
            action_type=ActionType.SCROLL,
            target_description=original_action.target_description,
            value="down",
            reasoning="Scroll to make the target element visible",
            success_criteria="Target element should become visible",
        )

    if cause == FailureRootCause.PAGE_NOT_LOADED:
        return BrowserAction(
            action_type=ActionType.WAIT,
            target_description="page to load",
            value="3",
            reasoning="Wait for page to finish loading",
            success_criteria="Page content should be available",
        )

    if cause in (FailureRootCause.SELECTOR_CHANGED, FailureRootCause.ELEMENT_NOT_FOUND):
        # If the LLM suggested an alternative target (e.g. "the [button] 'Submit'
        # instead of 'Search'"), use that as the new target_description. This
        # is the substantive part of self-correction — not just retrying the
        # same target with a cleared selector.
        new_target = _extract_target_from_recovery(
            diagnosis.recovery_strategy, original_action.target_description, page_state
        )
        return BrowserAction(
            action_type=original_action.action_type,
            target_description=new_target,
            value=original_action.value,
            selector="",  # Clear CSS selector to force AOM/semantic retry
            reasoning=f"Retrying with alternative locator '{new_target}' after: {diagnosis.explanation[:80]}",
            success_criteria=original_action.success_criteria,
        )

    if cause == FailureRootCause.WRONG_PAGE:
        return BrowserAction(
            action_type=ActionType.NAVIGATE,
            target_description="Go back to previous page",
            value="javascript:history.back()",
            reasoning="Navigate back — landed on wrong page",
            success_criteria="Return to the intended page",
        )

    return None


def _extract_target_from_recovery(
    recovery_strategy: str,
    fallback_target: str,
    page_state: PageState,
) -> str:
    """Extract a usable target description from the LLM's recovery suggestion.

    The healer LLM often replies with "Click [button] 'Submit'" or
    "Try locating element with role=textbox name='Customer Name'". We pull
    out the role+name pair and return it in a form the executor can locate.
    Falls back to the original target if no clear alternative is suggested.
    """
    if not recovery_strategy:
        return fallback_target

    text = recovery_strategy.strip()
    # Pattern 1: [role] "name"
    import re as _re
    m = _re.search(r"\[(\w+)\]\s*['\"]([^'\"]+)['\"]", text)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    # Pattern 2: role=X name=Y or role=X name='Y'
    m = _re.search(r"role[=:]\s*(\w+).{0,15}name[=:]\s*['\"]?([^'\"]+?)['\"]?(?:\s|$|,|\.)", text)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    # Pattern 3: explicit "the X 'Y'" or "X labelled 'Y'"
    m = _re.search(r"(button|link|textbox|searchbox|field|input|tab|menuitem)\s+(?:labelled|named|with text)?\s*['\"]([^'\"]+)['\"]", text, _re.IGNORECASE)
    if m:
        return f"{m.group(1).lower()} {m.group(2)}"
    # If recovery describes a different target without quotes (e.g. "Click the Submit button"),
    # truncate to a usable target description
    if len(text) < 80 and any(t in text.lower() for t in ("click", "select", "fill", "press")):
        # Strip leading verb
        cleaned = _re.sub(r"^(click|tap|select|fill|press)\s+(?:the\s+)?", "", text, flags=_re.IGNORECASE)
        return cleaned[:60]
    return fallback_target
