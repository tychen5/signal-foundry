"""
Observer: Page state capture and post-action verification.

Captures accessibility tree, visible text, and page metadata.
Provides post-action verification to prevent silent failures.
"""

from __future__ import annotations

import re
import time

from playwright.async_api import Page

from src.shared.logger import get_logger
from src.task2_browser.schemas import PageState, VerificationResult

logger = get_logger("observer")

# Max chars for accessibility tree snapshot to keep LLM context manageable
_MAX_A11Y_CHARS = 8000  # was 4000 — Wikipedia infoboxes / Yahoo Finance quote panels often appear past 4 kB
_MAX_TEXT_CHARS = 6000  # was 2000 — data-heavy pages (Wikipedia infoboxes, financial quote panels) need more context


async def observe(page: Page, screenshot_dir: str = "") -> PageState:
    """
    Capture the current page state for the LLM to reason about.

    Strategy:
    1. Accessibility tree (AOM) — most reliable for element identification
    2. Page metadata (URL, title)
    3. Visible text summary
    4. Error indicator detection

    Args:
        page: Playwright Page object
        screenshot_dir: Directory to save screenshots (empty = skip)

    Returns:
        PageState with all captured information
    """
    state = PageState()

    try:
        state.url = page.url
        state.title = await page.title()
    except Exception as e:
        logger.warning("observe_metadata_failed", error=str(e))

    # Accessibility tree snapshot (Layer 1 — most stable signal)
    # Playwright ≥1.46 removed the old accessibility snapshot API; the new
    # aria_snapshot() method lives on Locator, not on the Page object directly.
    try:
        a11y_text: str = await page.locator("body").aria_snapshot()
        if a11y_text:
            state.accessibility_tree = a11y_text[:_MAX_A11Y_CHARS]
            lower = a11y_text.lower()
            state.has_buttons = "button" in lower
            state.has_input_fields = "textbox" in lower or "searchbox" in lower
            state.has_links = "link" in lower
    except Exception as e:
        logger.warning("a11y_snapshot_failed", error=str(e))

    # Visible text summary
    try:
        body_text = await page.evaluate("() => document.body?.innerText || ''")
        state.visible_text_summary = _summarize_text(body_text)
    except Exception as e:
        logger.warning("text_extraction_failed", error=str(e))

    # Error indicator detection (silent failure prevention)
    try:
        state.error_indicators = await _detect_errors(page)
    except Exception:
        pass

    # Screenshot
    if screenshot_dir:
        try:
            import os

            os.makedirs(screenshot_dir, exist_ok=True)
            ts = int(time.time() * 1000)
            path = os.path.join(screenshot_dir, f"step_{ts}.png")
            await page.screenshot(path=path, full_page=False)
            state.screenshot_path = path
        except Exception as e:
            logger.warning("screenshot_failed", error=str(e))

    return state


def _format_a11y_tree(node: dict, depth: int = 0, max_depth: int = 5) -> str:
    """
    Format accessibility tree into a compact text representation.

    Filters out non-interactive/non-informative nodes to keep context small.
    """
    if depth > max_depth:
        return ""

    lines: list[str] = []
    role = node.get("role", "")
    name = node.get("name", "")
    value = node.get("value", "")

    # Only include meaningful nodes
    important_roles = {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "checkbox",
        "radio",
        "tab",
        "menuitem",
        "heading",
        "img",
        "navigation",
        "main",
        "form",
        "dialog",
        "alert",
        "banner",
        "contentinfo",
        "option",
        "listitem",
    }

    include = role.lower() in important_roles or (name and role)

    if include and (name or value):
        indent = "  " * depth
        parts = [f"{indent}[{role}]"]
        if name:
            parts.append(f'"{name[:80]}"')
        if value:
            parts.append(f"value={value[:40]}")
        # Include relevant states
        for attr in ("checked", "selected", "disabled", "expanded", "required"):
            if node.get(attr) is not None:
                parts.append(f"{attr}={node[attr]}")
        lines.append(" ".join(parts))

    # Recurse into children
    for child in node.get("children", []):
        child_text = _format_a11y_tree(child, depth + 1, max_depth)
        if child_text:
            lines.append(child_text)

    result = "\n".join(lines)
    return result[:_MAX_A11Y_CHARS]


def _summarize_text(full_text: str) -> str:
    """Summarize page text to fit LLM context window."""
    # Clean excessive whitespace
    text = re.sub(r"\s+", " ", full_text).strip()
    if len(text) <= _MAX_TEXT_CHARS:
        return text
    # Take beginning + end for context
    return text[: _MAX_TEXT_CHARS // 2] + "\n...\n" + text[-_MAX_TEXT_CHARS // 4 :]


async def _detect_errors(page: Page) -> list[str]:
    """
    Detect error indicators on the page (toasts, alerts, error messages).

    This is critical for silent failure prevention — catching cases where
    the action appeared to work but actually produced an error.
    """
    errors: list[str] = []

    try:
        # Check for common error patterns in page text
        error_text = await page.evaluate("""() => {
            const selectors = [
                '.error', '.alert-danger', '.alert-error', '.toast-error',
                '[role="alert"]', '.notification-error', '.error-message',
                '.form-error', '.field-error', '.invalid-feedback',
            ];
            const results = [];
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    const text = el.innerText?.trim();
                    if (text && text.length < 200) results.push(text);
                }
            }
            return results;
        }""")
        errors.extend(error_text[:5])  # Cap at 5 error indicators
    except Exception:
        pass

    return errors


async def verify_action(
    before: PageState,
    after: PageState,
    intended_action: str,
) -> VerificationResult:
    """
    Deterministic post-action verification (no LLM needed for basic checks).

    Checks whether the page actually changed in a way consistent with the action.

    Args:
        before: Page state before the action
        after: Page state after the action
        intended_action: Description of what was intended

    Returns:
        VerificationResult with confidence score
    """
    result = VerificationResult()

    # Check URL change
    result.url_changed = before.url != after.url

    # Check DOM/text change
    result.dom_changed = (
        before.visible_text_summary != after.visible_text_summary
        or before.accessibility_tree != after.accessibility_tree
    )

    result.state_changed = result.url_changed or result.dom_changed

    # Check for new errors
    new_errors = [e for e in after.error_indicators if e not in before.error_indicators]
    if new_errors:
        result.success = False
        result.confidence = 0.2
        result.reason = f"New errors detected: {'; '.join(new_errors[:2])}"
        return result

    # Action-specific verification
    action_lower = intended_action.lower()

    if "navigate" in action_lower or "go to" in action_lower:
        result.success = result.url_changed
        result.confidence = 0.9 if result.url_changed else 0.3
        result.reason = "URL changed" if result.url_changed else "URL did not change after navigation"

    elif "click" in action_lower:
        result.success = result.state_changed
        result.confidence = 0.8 if result.state_changed else 0.4
        result.reason = "Page state changed after click" if result.state_changed else "No observable change after click"

    elif "fill" in action_lower or "type" in action_lower:
        # Filling a field may not change the observable text summary much
        result.success = True
        result.confidence = 0.7
        result.reason = "Fill action performed"

    elif "extract" in action_lower or "read" in action_lower:
        result.success = True
        result.confidence = 0.9
        result.reason = "Extract action — data captured from page state"

    elif "scroll" in action_lower:
        result.success = True
        result.confidence = 0.8
        result.reason = "Scroll action performed"

    elif "wait" in action_lower:
        result.success = True
        result.confidence = 0.9
        result.reason = "Wait completed"

    else:
        result.success = result.state_changed
        result.confidence = 0.6 if result.state_changed else 0.4
        result.reason = "Generic action verification"

    return result
