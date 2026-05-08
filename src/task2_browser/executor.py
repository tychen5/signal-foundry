"""
Executor: Playwright browser action execution with 3-layer locator fallback.

Layer 1: Accessibility Tree (AOM) — most stable across UI changes
Layer 2: Semantic DOM (aria-label, data-testid, placeholder, text content)
Layer 3: CSS selector fallback

Each action captures before/after state for verification.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.shared.logger import get_logger
from src.task2_browser.schemas import (
    ActionType,
    BrowserAction,
    LocatorStrategy,
)

logger = get_logger("executor")

# Default timeout for element interactions (ms)
_DEFAULT_TIMEOUT = 8000
_NAVIGATION_TIMEOUT = 15000


async def execute_action(
    page: Page,
    action: BrowserAction,
) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """
    Execute a single browser action using the 3-layer locator fallback.

    Args:
        page: Playwright page
        action: Action to execute

    Returns:
        Tuple of (success, locator_strategy_used, error_message)
    """
    try:
        if action.action_type == ActionType.NAVIGATE:
            return await _execute_navigate(page, action)
        elif action.action_type == ActionType.CLICK:
            return await _execute_click(page, action)
        elif action.action_type == ActionType.FILL:
            return await _execute_fill(page, action)
        elif action.action_type == ActionType.SELECT:
            return await _execute_select(page, action)
        elif action.action_type == ActionType.SCROLL:
            return await _execute_scroll(page, action)
        elif action.action_type == ActionType.WAIT:
            return await _execute_wait(page, action)
        elif action.action_type == ActionType.KEY_PRESS:
            return await _execute_key_press(page, action)
        elif action.action_type == ActionType.HOVER:
            return await _execute_hover(page, action)
        elif action.action_type == ActionType.EXTRACT:
            return True, None, None  # Extract is handled by observer
        elif action.action_type == ActionType.DONE:
            return True, None, None
        elif action.action_type == ActionType.SCREENSHOT:
            return True, None, None  # Screenshot handled by observer
        else:
            return False, None, f"Unknown action type: {action.action_type}"
    except Exception as e:
        logger.warning("action_execution_failed", action=action.action_type.value, error=str(e))
        return False, None, str(e)


async def _execute_navigate(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Navigate to a URL."""
    url = action.value or action.target_description
    if not url:
        return False, None, "No URL provided for navigation"

    # Ensure URL has scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT)
        # Wait a moment for dynamic content
        await asyncio.sleep(0.5)
        return True, None, None
    except PlaywrightTimeout:
        # Page may have partially loaded — check if URL changed
        if page.url != "about:blank":
            return True, None, None
        return False, None, f"Navigation timeout: {url}"
    except Exception as e:
        return False, None, f"Navigation failed: {str(e)}"


async def _execute_click(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Click an element using 3-layer locator fallback."""
    target = action.target_description
    selector = action.selector

    # Layer 1: Accessibility-based locator (most stable)
    strategy, error = await _try_a11y_click(page, target)
    if strategy:
        return True, strategy, None

    # Layer 2: Semantic DOM locator
    strategy, error = await _try_semantic_click(page, target)
    if strategy:
        return True, strategy, None

    # Layer 3: CSS selector fallback
    if selector:
        strategy, error = await _try_css_click(page, selector)
        if strategy:
            return True, strategy, None

    # Layer 2b: Text content match (last resort before failing)
    strategy, error = await _try_text_click(page, target)
    if strategy:
        return True, strategy, None

    return False, None, f"Could not locate element to click: '{target}'. Last error: {error}"


async def _try_a11y_click(page: Page, target: str) -> tuple[Optional[LocatorStrategy], Optional[str]]:
    """Layer 1: Try clicking via accessibility role + name."""
    target_lower = target.lower()

    # Map common descriptions to roles
    role_mappings = [
        ("button", "button"),
        ("link", "link"),
        ("tab", "tab"),
        ("checkbox", "checkbox"),
        ("radio", "radio"),
        ("menuitem", "menuitem"),
        ("option", "option"),
        ("search", "searchbox"),
    ]

    for keyword, role in role_mappings:
        if keyword in target_lower:
            # Extract the name part (remove the role keyword)
            name_part = target_lower.replace(keyword, "").strip().strip("'\"")
            if name_part:
                try:
                    locator = page.get_by_role(role, name=name_part, exact=False)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=_DEFAULT_TIMEOUT)
                        return LocatorStrategy.ACCESSIBILITY, None
                except Exception:
                    pass

    # Try generic role-based locator with the full target as name
    for role in ["button", "link", "tab", "menuitem"]:
        try:
            locator = page.get_by_role(role, name=target, exact=False)
            if await locator.count() > 0:
                await locator.first.click(timeout=_DEFAULT_TIMEOUT)
                return LocatorStrategy.ACCESSIBILITY, None
        except Exception:
            pass

    return None, "No accessibility match found"


async def _try_semantic_click(page: Page, target: str) -> tuple[Optional[LocatorStrategy], Optional[str]]:
    """Layer 2: Try clicking via semantic DOM attributes."""
    target_lower = target.lower()

    # Try aria-label
    try:
        locator = page.locator(f'[aria-label*="{target}" i]')
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Try data-testid
    try:
        locator = page.locator(f'[data-testid*="{target_lower}"]')
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Try placeholder (for inputs that look like buttons)
    try:
        locator = page.get_by_placeholder(target, exact=False)
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Try title attribute
    try:
        locator = page.locator(f'[title*="{target}" i]')
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    return None, "No semantic DOM match found"


async def _try_text_click(page: Page, target: str) -> tuple[Optional[LocatorStrategy], Optional[str]]:
    """Layer 2b: Try clicking by visible text content."""
    try:
        locator = page.get_by_text(target, exact=False)
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return LocatorStrategy.TEXT_CONTENT, None
    except Exception as e:
        return None, str(e)

    return None, "No text content match found"


async def _try_css_click(page: Page, selector: str) -> tuple[Optional[LocatorStrategy], Optional[str]]:
    """Layer 3: Try clicking via CSS selector."""
    try:
        locator = page.locator(selector)
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return LocatorStrategy.CSS_SELECTOR, None
    except Exception as e:
        return None, str(e)

    return None, f"CSS selector not found: {selector}"


async def _execute_fill(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Fill a text input using 3-layer locator fallback."""
    target = action.target_description
    value = action.value

    if not value:
        return False, None, "No value to fill"

    # Layer 1: Accessibility-based
    for role in ["textbox", "searchbox", "combobox"]:
        try:
            locator = page.get_by_role(role, name=target, exact=False)
            if await locator.count() > 0:
                await locator.first.fill(value, timeout=_DEFAULT_TIMEOUT)
                return True, LocatorStrategy.ACCESSIBILITY, None
        except Exception:
            pass

    # Layer 2: Placeholder
    try:
        locator = page.get_by_placeholder(target, exact=False)
        if await locator.count() > 0:
            await locator.first.fill(value, timeout=_DEFAULT_TIMEOUT)
            return True, LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Layer 2: Label
    try:
        locator = page.get_by_label(target, exact=False)
        if await locator.count() > 0:
            await locator.first.fill(value, timeout=_DEFAULT_TIMEOUT)
            return True, LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Layer 2: aria-label
    try:
        locator = page.locator(f'[aria-label*="{target}" i]')
        if await locator.count() > 0:
            await locator.first.fill(value, timeout=_DEFAULT_TIMEOUT)
            return True, LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Layer 3: CSS selector
    if action.selector:
        try:
            locator = page.locator(action.selector)
            if await locator.count() > 0:
                await locator.first.fill(value, timeout=_DEFAULT_TIMEOUT)
                return True, LocatorStrategy.CSS_SELECTOR, None
        except Exception:
            pass

    # Last resort: find any visible input
    try:
        locator = page.locator("input:visible, textarea:visible").first
        await locator.fill(value, timeout=_DEFAULT_TIMEOUT)
        return True, LocatorStrategy.CSS_SELECTOR, None
    except Exception as e:
        return False, None, f"Could not find input to fill: {str(e)}"


async def _execute_select(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Select an option from a dropdown/radio/checkbox.

    The agent's `select` action covers three native HTML controls that all
    behave differently:
      1. <select><option> dropdown — needs select_option(label=...)
      2. <input type=radio> — needs check() on the labelled radio
      3. <input type=checkbox> — needs check() on the labelled checkbox
    The fix: detect which one is present and call the right method, rather
    than blindly calling select_option (which fails on radio/checkbox).
    """
    target = action.target_description
    value = action.value

    # Strategy A: True <select> dropdown via label or role
    try:
        locator = page.get_by_role("combobox", name=target, exact=False)
        if await locator.count() > 0:
            await locator.first.select_option(label=value, timeout=_DEFAULT_TIMEOUT)
            return True, LocatorStrategy.ACCESSIBILITY, None
    except Exception:
        pass

    # Strategy B: Radio button by visible value (the most common form-fill pattern)
    for role in ("radio", "checkbox"):
        try:
            locator = page.get_by_role(role, name=value, exact=False)
            if await locator.count() > 0:
                await locator.first.check(timeout=_DEFAULT_TIMEOUT)
                return True, LocatorStrategy.ACCESSIBILITY, None
        except Exception:
            pass

    # Strategy C: Label-based selection (handles `<label>X<input></label>`)
    try:
        locator = page.get_by_label(value, exact=False)
        if await locator.count() > 0:
            try:
                await locator.first.check(timeout=_DEFAULT_TIMEOUT)
                return True, LocatorStrategy.SEMANTIC_DOM, None
            except Exception:
                # If check() fails (e.g., it's actually a select), try select_option
                await locator.first.select_option(label=value, timeout=_DEFAULT_TIMEOUT)
                return True, LocatorStrategy.SEMANTIC_DOM, None
    except Exception:
        pass

    # Strategy D: Click the option text directly (custom dropdowns)
    try:
        locator = page.get_by_text(value, exact=False)
        if await locator.count() > 0:
            await locator.first.click(timeout=_DEFAULT_TIMEOUT)
            return True, LocatorStrategy.TEXT_CONTENT, None
    except Exception as e:
        return False, None, f"Could not select '{value}': {str(e)}"

    return False, None, f"No locator strategy found for select '{target}' = '{value}'"


async def _execute_scroll(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Scroll the page."""
    direction = action.value.lower() if action.value else "down"
    pixels = 500

    try:
        if direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{pixels})")
        elif direction == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            await page.evaluate("window.scrollTo(0, 0)")
        else:
            await page.evaluate(f"window.scrollBy(0, {pixels})")
        await asyncio.sleep(0.3)
        return True, None, None
    except Exception as e:
        return False, None, f"Scroll failed: {str(e)}"


async def _execute_wait(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Wait for a condition or fixed duration.

    The prompt instructs the LLM to pass `value` in milliseconds. Some
    LLMs interpret this literally (`"2000"`) and some pass seconds
    (`"2"`). We auto-detect: anything >= 100 is treated as ms.
    """
    wait_time = 2.0  # Default 2 seconds

    try:
        if action.value:
            wait_val = float(action.value)
            if wait_val >= 100:
                wait_val = wait_val / 1000.0
            wait_time = max(0.1, min(wait_val, 10.0))
    except (ValueError, TypeError):
        pass

    # When agent issues a `wait`, also try `wait_for_load_state` to
    # ride out async hydration. Don't fail if it times out — the fixed
    # sleep below is the floor.
    try:
        await page.wait_for_load_state("networkidle", timeout=int(wait_time * 1000))
    except Exception:
        pass

    await asyncio.sleep(wait_time)
    return True, None, None


async def _execute_key_press(
    page: Page, action: BrowserAction
) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Press a keyboard key."""
    key = action.value or "Enter"
    try:
        await page.keyboard.press(key)
        await asyncio.sleep(0.3)
        return True, None, None
    except Exception as e:
        return False, None, f"Key press failed: {str(e)}"


async def _execute_hover(page: Page, action: BrowserAction) -> tuple[bool, Optional[LocatorStrategy], Optional[str]]:
    """Hover over an element."""
    target = action.target_description

    try:
        locator = page.get_by_text(target, exact=False)
        if await locator.count() > 0:
            await locator.first.hover(timeout=_DEFAULT_TIMEOUT)
            return True, LocatorStrategy.TEXT_CONTENT, None
    except Exception:
        pass

    for role in ["button", "link", "menuitem"]:
        try:
            locator = page.get_by_role(role, name=target, exact=False)
            if await locator.count() > 0:
                await locator.first.hover(timeout=_DEFAULT_TIMEOUT)
                return True, LocatorStrategy.ACCESSIBILITY, None
        except Exception:
            pass

    return False, None, f"Could not find element to hover: '{target}'"


async def dismiss_popups(page: Page) -> bool:
    """
    Attempt to dismiss common popups (cookie banners, newsletters, etc.).

    Returns True if any popup was dismissed.
    """
    dismissed = False

    # Common cookie/consent button patterns + multilingual variants.
    # Order matters: try the most specific (button:has-text) before fallbacks.
    consent_patterns = [
        # English buttons
        'button:has-text("Accept All")',
        'button:has-text("Accept all cookies")',
        'button:has-text("Accept")',
        'button:has-text("Accept Cookies")',
        'button:has-text("I Agree")',
        'button:has-text("Agree")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        'button:has-text("Allow")',
        'button:has-text("Consent")',
        'button:has-text("Continue")',
        'button:has-text("Allow all")',
        'button:has-text("Confirm")',
        # Chinese (Traditional + Simplified) — common on TWSE, cnyes, Yahoo TW
        'button:has-text("接受")',
        'button:has-text("同意")',
        'button:has-text("確定")',
        'button:has-text("我同意")',
        'button:has-text("接受全部")',
        # Japanese
        'button:has-text("同意する")',
        'button:has-text("承諾")',
        'button:has-text("すべて同意")',
        # German (DE/AT/CH — extremely common on EU news sites)
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Akzeptieren")',
        'button:has-text("Zustimmen")',
        'button:has-text("Einverstanden")',
        # Spanish
        'button:has-text("Aceptar todo")',
        'button:has-text("Aceptar")',
        'button:has-text("De acuerdo")',
        # French
        'button:has-text("Tout accepter")',
        'button:has-text("Accepter")',
        "button:has-text(\"J'accepte\")",
        # Korean
        'button:has-text("수락")',
        'button:has-text("동의")',
        'button:has-text("모두 동의")',
        # GDPR-style links/divs
        '[id*="accept" i]',
        '[id*="consent" i]',
        '[class*="accept-cookies" i]',
        '[class*="cookie-accept" i]',
        '[class*="consent-button" i]',
        '[aria-label*="accept" i]',
        '[aria-label*="cookie" i]',
        '[aria-label*="close" i]',
        '[aria-label*="dismiss" i]',
        # Newsletter/modal close buttons
        'button[aria-label*="close" i]',
        'button[aria-label*="dismiss" i]',
        'button.close',
        # Major CMP (Consent Management Platform) selectors
        '#onetrust-accept-btn-handler',  # OneTrust — very common on US news
        '#truste-consent-button',
        '.osano-cm-accept-all',
        # Quantcast Choice (NYT, Forbes, Reuters)
        'button.qc-cmp2-summary-buttons[mode="primary"]',
        'button[aria-label="AGREE"]',
        # CookieYes / Cookiebot
        '#cky-btn-accept',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        # Didomi (used by Le Monde, France TV, Microsoft)
        '#didomi-notice-agree-button',
        # Sourcepoint (EU news / publisher CMP)
        'button[title="Accept All"]',
        # Usercentrics
        'button[data-testid="uc-accept-all-button"]',
    ]

    for pattern in consent_patterns:
        try:
            locator = page.locator(pattern).first
            if await locator.is_visible(timeout=500):
                await locator.click(timeout=2000)
                dismissed = True
                await asyncio.sleep(0.5)
                logger.info("popup_dismissed", pattern=pattern[:50])
                break
        except Exception:
            continue

    # Close any dialogs
    try:
        page.on("dialog", lambda dialog: dialog.dismiss())
    except Exception:
        pass

    return dismissed
