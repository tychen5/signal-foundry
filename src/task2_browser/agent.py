"""
Browser Automation Agent: Main orchestrator.

Implements the Observe → Think → Act → Verify loop:
1. Planner decomposes task into steps (or uses reactive planning)
2. Observer captures page state (accessibility tree + DOM + screenshot)
3. Executor runs actions with 3-layer AOM-first locator fallback
4. Verifier checks for silent failures after each action
5. Healer diagnoses root cause and suggests recovery on failure

Key innovation: NOT just try/except retry — the Healer classifies the
root cause (selector_changed vs page_not_loaded vs popup) and selects
a targeted recovery strategy.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

from playwright.async_api import async_playwright

from src.shared.cost_tracker import get_cost_tracker
from src.shared.logger import generate_trace_id, get_logger
from src.shared.tracing import attach_metadata, traced
from src.task2_browser.executor import dismiss_popups, execute_action
from src.task2_browser.healer import (
    diagnose_deterministic,
    diagnose_with_llm,
    suggest_alternative_action,
)
from src.task2_browser.observer import observe, verify_action
from src.task2_browser.planner import decide_next_action, plan_task, verify_with_llm
from src.task2_browser.schemas import (
    ActionType,
    AgentResult,
    BrowserAction,
    StepResult,
)

logger = get_logger("browser_agent")
cost_tracker = get_cost_tracker()

# Maximum healing attempts per step before giving up
_MAX_HEAL_ATTEMPTS = 3
# Verification confidence threshold — below this triggers healing
_VERIFICATION_THRESHOLD = 0.4

# Phrases that indicate the LLM is hedging or didn't actually find an answer.
# When the final_answer matches one of these, downgrade status to "not_found"
# instead of claiming "success" — this is the silent-failure guard.
_NOT_FOUND_PHRASES = (
    # English: information genuinely missing
    "i cannot find",
    "i could not find",
    "i was unable to find",
    "i don't have access",
    "i do not have access",
    "no such information",
    "not available on the page",
    "the page does not contain",
    "i'm not able to determine",
    "cannot determine",
    "cannot be found",
    "this page does not have",
    "no information about",
    "unable to retrieve",
    "unable to extract",
    "could not be retrieved",
    "no contact information",
    "no information is available",
    # English: structured not-found / not-accessible markers (v2 actor prompt)
    "not_found:",
    "not_accessible:",
    "not accessible:",
    # English: site-blocking / protection
    "blocked by",
    "behind a paywall",
    "behind an authwall",
    "behind a login wall",
    "authwall requiring",
    "captcha challenge",
    "anti-bot",
    "verification iframe",
    "press & hold to confirm",
    "404 not found",
    "page does not exist",
    "404 error",
    "checking your browser",  # Cloudflare interstitial
    "just a moment",  # Cloudflare "checking" interstitial
    "verify you are human",
    "please complete the security check",
    "rate limit exceeded",
    "you have been rate limited",
    "service unavailable",
    "temporarily unavailable",
    "maintenance mode",
    "site is undergoing maintenance",
    "not available in your region",
    "geo-restricted",
    "region not supported",
    "access denied",  # generic 403
    # Chinese
    "未能找到",
    "找不到",
    "無法找到",
    "無法取得",
    "頁面沒有",
    "頁面不存在",
    "需要登入",
    "需要登錄",
    "需要登录",
    "請先登入",
    "请先登录",
    "您所在地區",
    "暫不開放",
    "暂不开放",
    "维护中",
    "維護中",
    # Japanese
    "ログインが必要",
    "ページが見つかりません",
    "メンテナンス中",
    "現在ご利用いただけません",
)

_NUMBER_TOKEN = re.compile(r"\d{2,}(?:[.,]\d+)?")


def _detect_stuck_loop(action_history: list, step_results: list) -> bool:
    """Return True iff the agent has repeated the *same* action 3 times in a
    row without the URL changing.

    The agent's reactive loop calls the LLM each turn to pick the next
    action. When the LLM gets confused (broken button, captcha that won't
    accept input, form field that resets on submit), it can latch onto the
    same action for many consecutive steps, burning through max_steps
    without progress.

    We compare the last 3 entries of ``action_history`` (free-form
    `action_type: target` strings the agent already maintains for context)
    AND the URLs of the last 3 step results — both must be identical for
    the loop to fire. Distinct heuristics: a healed retry with a different
    selector won't have an identical action_history entry; a redirect
    cycle (same action, different URLs) won't have identical URLs.

    Returns False unless we have at least 3 prior reactive steps.
    """
    if len(action_history) < 3 or len(step_results) < 3:
        return False
    recent_actions = action_history[-3:]
    if not (recent_actions[0] == recent_actions[1] == recent_actions[2]):
        return False
    recent_urls = [(s.after_state.url if s.after_state else "") for s in step_results[-3:]]
    return len(set(recent_urls)) == 1


def _clean_final_answer(answer: str) -> str:
    """Strip LLM markdown / JSON wrapping from a final-answer string.

    Some models wrap their response in ```json ...``` or output a JSON
    object literally (`{"complete": true, "answer": "X"}`) when the actor
    prompt says to put the answer in `value` directly. Pull out the inner
    `answer` / `final_answer` field and return that, or fall back to the
    raw string with the code-fence stripped.
    """
    if not answer:
        return answer
    text = answer.strip()
    # Strip markdown code-fence wrappers
    if text.startswith("```"):
        # Remove leading ```json\n or ```\n
        lines = text.split("\n", 1)
        if len(lines) > 1:
            text = lines[1]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    # Try to extract a JSON answer field
    try:
        import json as _json

        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            obj = _json.loads(m.group())
            if isinstance(obj, dict):
                inner = obj.get("answer") or obj.get("final_answer") or obj.get("value")
                if isinstance(inner, str):
                    return inner.strip()
    except (ValueError, TypeError):
        pass
    return text


# URL substring markers that indicate the final page is NOT the requested
# content. These are deterministic — no LLM needed. If any appear in the
# final URL, the silent-failure guard flips status to not_found.
_BLOCKED_URL_MARKERS = (
    # Auth walls
    "/authwall",  # LinkedIn auth redirect
    "/login?",  # generic login redirect (with query string)
    "/login/",
    "/signin?",
    "/signin/",
    "accounts.google.com/signin",
    "accounts.google.com/v3/signin",
    "/checkpoint/challenge",  # Facebook
    "/sso/login",
    "/oauth/authorize",
    "auth0.com/login",  # Auth0 hosted login
    "/saml2/idp",  # SAML IdP redirect
    # Anti-bot challenges
    "/recaptcha",
    "/cf-chl",  # Cloudflare challenge (legacy)
    "__cf_chl",  # Cloudflare challenge (newer URL param)
    "/captcha",
    "/hcaptcha",
    "/turnstile",  # Cloudflare Turnstile
    "px-captcha",  # PerimeterX
    # Access-denied / geo-block / region-block
    "/access-denied",
    "/blocked",
    "/region-not-supported",
    "/not-available-in-your-region",
    "/age-verification",
    "/age-gate",
    # Error / maintenance pages
    "/maintenance",
    "/server-error",
    "/error/500",
    "/error/503",
    "edgar/error",  # SEC EDGAR error page
)


class BrowserAgent:
    """
    Self-healing browser automation agent.

    Architecture:
    - Planner: LLM decomposes task into steps
    - Executor: Playwright runs actions with AOM-first locators
    - Observer: Captures page state for verification
    - Healer: Diagnoses failures and suggests recovery
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        user_api_key: Optional[str] = None,
        headless: bool = True,
        screenshot_dir: str = "/tmp/signal_foundry_browser",
        use_vision: bool = False,
        progress_callback: Optional[callable] = None,
    ):
        self.model_name = model_name
        self.user_api_key = user_api_key
        self.headless = headless
        self.screenshot_dir = screenshot_dir
        # Multi-modal vision: only effective with gemini/claude/gpt-5.5.
        # When True and the model supports it, the verifier receives the
        # current viewport as an inline JPEG alongside the AOM text.
        self.use_vision = use_vision
        # Optional async callback for live progress streaming. The agent
        # awaits this with a dict event after each milestone (plan_done,
        # step_start, step_done, healer_active, agent_complete). Used by
        # the SSE endpoint to push intermediate state to the UI.
        self.progress_callback = progress_callback

    async def _emit(self, event: str, **payload) -> None:
        """Best-effort progress emit; never let a callback failure break the run."""
        if not self.progress_callback:
            return
        try:
            await self.progress_callback({"event": event, **payload})
        except Exception as e:
            logger.warning("progress_callback_failed", error=str(e)[:120])

    @traced(name="task2_browser_agent_run", tags=["task2", "browser_agent"])
    async def run(
        self,
        task_description: str,
        target_url: Optional[str] = None,
        max_steps: int = 20,
        trace_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Execute a browser automation task.

        Args:
            task_description: Natural language task
            target_url: Starting URL (optional)
            max_steps: Maximum steps before timeout
            trace_id: Request trace ID

        Returns:
            AgentResult with full execution trace
        """
        if trace_id is None:
            trace_id = generate_trace_id()

        attach_metadata(
            {
                "trace_id": trace_id,
                "task_description": task_description[:200],
                "target_url": target_url or "",
                "max_steps": max_steps,
                "model_name": self.model_name or "default",
                "use_vision": self.use_vision,
            }
        )

        start_time = time.time()
        result = AgentResult(
            trace_id=trace_id,
            task_description=task_description,
            target_url=target_url or "",
        )
        result.metadata["model_name"] = self.model_name or "default"
        result.metadata["use_vision_requested"] = self.use_vision

        # Vision history: rolling buffer of the last N screenshots labelled
        # by step number. Only populated when use_vision=True and model is
        # vision-capable. Configurable via T2_VISION_HISTORY_MAX env var
        # (default 3) — the LLM mostly cares about the chronological diff.
        vision_history: list[tuple[str, str]] = []
        _vision_is_active = False
        if self.use_vision:
            from src.task2_browser.vision import is_vision_capable, vision_history_max

            _vision_is_active = is_vision_capable(self.model_name)
            _max_vision_hist = vision_history_max()
        else:
            _max_vision_hist = 3
        result.metadata["use_vision_active"] = _vision_is_active

        async def capture_vision_snapshot(page, label: str, *, full_page: bool = False) -> Optional[str]:
            """Capture and append one bounded vision snapshot when active."""
            if not _vision_is_active:
                return None
            from src.task2_browser.vision import (
                capture_full_page_screenshot_b64,
                capture_screenshot_b64,
            )

            screenshot = (
                await capture_full_page_screenshot_b64(page) if full_page else await capture_screenshot_b64(page)
            )
            if screenshot:
                vision_history.append((label, screenshot))
                if len(vision_history) > _max_vision_hist:
                    vision_history.pop(0)
            return screenshot

        logger.info(
            "agent_start",
            task=task_description[:100],
            url=target_url,
            max_steps=max_steps,
            trace_id=trace_id,
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            try:
                await self._emit(
                    "phase_start",
                    phase="plan",
                    task=task_description[:200],
                    model=self.model_name,
                    use_vision=self.use_vision,
                )
                # Phase 1: Plan the task
                plan = await plan_task(
                    task_description=task_description,
                    target_url=target_url,
                    model_name=self.model_name,
                    user_api_key=self.user_api_key,
                    trace_id=trace_id,
                )
                result.metadata["plan_steps"] = len(plan.steps)
                result.metadata["estimated_complexity"] = plan.estimated_complexity
                await self._emit(
                    "phase_done",
                    phase="plan",
                    plan_steps=len(plan.steps),
                    plan_summary=[
                        {"action": s.action_type.value, "target": s.target_description[:80]} for s in plan.steps[:8]
                    ],
                )

                # Phase 2: Execute plan steps + reactive loop
                completed_step_descriptions: list[str] = []

                # Execute planned steps first
                for planned_action in plan.steps:
                    if result.total_steps >= max_steps:
                        break

                    await self._emit(
                        "step_start",
                        step=result.total_steps + 1,
                        action=planned_action.action_type.value,
                        target=planned_action.target_description[:120],
                        phase="planned",
                    )

                    step_result = await self._execute_step(
                        page=page,
                        action=planned_action,
                        step_number=result.total_steps + 1,
                        trace_id=trace_id,
                    )
                    result.steps.append(step_result)
                    result.total_steps += 1

                    if step_result.healer_activated:
                        result.healer_activations += 1
                        result.self_corrections += 1

                    await self._emit(
                        "step_done",
                        step=result.total_steps,
                        url=step_result.after_state.url if step_result.after_state else "",
                        healer=step_result.healer_activated,
                        diagnosis=step_result.healer_diagnosis or "",
                        confidence=(step_result.verification.confidence if step_result.verification else None),
                        error=step_result.error or "",
                    )

                    if step_result.after_state and step_result.after_state.screenshot_path:
                        result.screenshots.append(step_result.after_state.screenshot_path)

                    # Capture screenshot during planned steps too — gives
                    # the verifier temporal context from the very start
                    if _vision_is_active:
                        step_no = result.total_steps
                        await capture_vision_snapshot(page, f"step {step_no} planned")

                    # Track completed steps for context
                    action_desc = f"{step_result.action.action_type.value}: {step_result.action.target_description}"
                    if step_result.error:
                        action_desc += f" [FAILED: {step_result.error[:50]}]"
                    if step_result.extracted_data:
                        # Prepend the extracted text snippet to the next
                        # step's context so the LLM doesn't keep scrolling
                        # blindly looking for the answer it now has.
                        action_desc += f" [EXTRACTED: {step_result.extracted_data[:600]}]"
                    completed_step_descriptions.append(action_desc)

                # Phase 3: Reactive loop — keep acting until task is done
                for _ in range(max_steps - result.total_steps):
                    # Observe current state
                    current_state = await observe(page, self.screenshot_dir)

                    # Capture screenshot for multi-modal verification (opt-in).
                    # Only fires for vision-capable models — capture is cheap
                    # but the LLM cost is what we're guarding against.
                    screenshot_b64 = None
                    if _vision_is_active:
                        # Use a capped full-page capture when the task is
                        # explicitly visual or when AOM text is sparse. This
                        # helps charts/maps/image-heavy pages without sending
                        # huge screenshots on normal text pages.
                        visual_terms = ("chart", "graph", "map", "image", "canvas", "screenshot", "color")
                        wants_visual_context = any(term in task_description.lower() for term in visual_terms)
                        sparse_aom = len((current_state.visible_text_summary or "").strip()) < 400
                        step_no = result.total_steps + 1
                        screenshot_b64 = await capture_vision_snapshot(
                            page,
                            f"step {step_no} {'full page' if wants_visual_context or sparse_aom else 'viewport'}",
                            full_page=wants_visual_context or sparse_aom,
                        )

                    # Check if task is complete — pass the FULL vision history
                    # so the verifier can confirm action effects (modal
                    # dismissed, search completed, error toast appeared)
                    is_complete, answer, confidence = await verify_with_llm(
                        task_description=task_description,
                        page_state=current_state,
                        completed_steps=completed_step_descriptions,
                        model_name=self.model_name,
                        user_api_key=self.user_api_key,
                        trace_id=trace_id,
                        screenshot_b64=screenshot_b64,
                        screenshot_history=vision_history if len(vision_history) > 1 else None,
                    )
                    result.llm_calls += 1

                    if is_complete and confidence > 0.6:
                        result.final_answer = _clean_final_answer(answer)
                        result.status = "success"
                        break

                    # Decide next action — also pass screenshot history so
                    # the actor can detect loops (clicked button → no change)
                    # and choose a different strategy
                    next_action = await decide_next_action(
                        task_description=task_description,
                        page_state=current_state,
                        completed_steps=completed_step_descriptions,
                        model_name=self.model_name,
                        user_api_key=self.user_api_key,
                        trace_id=trace_id,
                        screenshot_b64=screenshot_b64,
                        screenshot_history=vision_history if len(vision_history) > 1 else None,
                    )
                    result.llm_calls += 1

                    if next_action.action_type == ActionType.DONE:
                        result.final_answer = _clean_final_answer(next_action.value or next_action.reasoning)
                        result.status = "success"
                        break

                    # Execute the action
                    step_result = await self._execute_step(
                        page=page,
                        action=next_action,
                        step_number=result.total_steps + 1,
                        trace_id=trace_id,
                    )
                    result.steps.append(step_result)
                    result.total_steps += 1

                    if step_result.healer_activated:
                        result.healer_activations += 1
                        result.self_corrections += 1

                    if step_result.after_state and step_result.after_state.screenshot_path:
                        result.screenshots.append(step_result.after_state.screenshot_path)

                    action_desc = f"{step_result.action.action_type.value}: {step_result.action.target_description}"
                    if step_result.error:
                        action_desc += f" [FAILED: {step_result.error[:50]}]"
                    if step_result.extracted_data:
                        # Prepend the extracted text snippet to the next
                        # step's context so the LLM doesn't keep scrolling
                        # blindly looking for the answer it now has.
                        action_desc += f" [EXTRACTED: {step_result.extracted_data[:600]}]"
                    completed_step_descriptions.append(action_desc)

                    # Stuck-loop guard: if the last 3 reactive-phase actions
                    # are identical AND none of them changed the URL, the
                    # planner is in a tight loop (typical pattern: clicking a
                    # broken button repeatedly, or filling a field that
                    # resets). Break out as `partial` rather than burn
                    # through max_steps repeating the same mistake.
                    if _detect_stuck_loop(completed_step_descriptions, result.steps):
                        logger.warning(
                            "stuck_loop_detected",
                            repeated_action=completed_step_descriptions[-1][:120],
                            trace_id=trace_id,
                        )
                        result.failure_modes.append("stuck_loop")
                        result.status = "partial"
                        last_url = result.steps[-1].after_state.url if result.steps[-1].after_state else ""
                        result.final_answer = (
                            f"Stuck repeating the same action 3x without "
                            f"page change: {completed_step_descriptions[-1][:200]}. "
                            f"Last URL: {last_url}"
                        )
                        break

                else:
                    # Reached max steps without completion
                    result.status = "partial"
                    current_state = await observe(page, self.screenshot_dir)
                    result.final_answer = f"Reached max steps ({max_steps}). Last page: {current_state.url}"

            except Exception as e:
                from src.shared.llm_errors import LLMStageError

                if isinstance(e, LLMStageError):
                    raise
                logger.error("agent_execution_error", error=str(e), trace_id=trace_id)
                result.status = "failed"
                result.final_answer = f"Agent error: {str(e)}"
                result.failure_modes.append(str(type(e).__name__))

            finally:
                await context.close()
                await browser.close()

        result.total_duration_ms = round((time.time() - start_time) * 1000, 1)
        request_cost = cost_tracker.get_request_cost(trace_id)
        result.cost_usd = request_cost.get("cost_usd", 0.0)

        # Silent-failure guard: even if the verifier said "is_complete=True",
        # downgrade the result if the answer is a hedge or the cited numbers
        # can't be sourced from observed page text.
        self._guard_against_silent_success(result)

        await self._emit(
            "agent_complete",
            status=result.status,
            steps=result.total_steps,
            self_corrections=result.self_corrections,
            cost_usd=result.cost_usd,
            duration_ms=result.total_duration_ms,
            answer=(result.final_answer or "")[:300],
            failure_modes=result.failure_modes,
        )

        logger.info(
            "agent_complete",
            status=result.status,
            steps=result.total_steps,
            self_corrections=result.self_corrections,
            duration_ms=result.total_duration_ms,
            trace_id=trace_id,
        )

        return result

    def _guard_against_silent_success(self, result: AgentResult) -> None:
        """Downgrade `success` / `partial` → `not_found` / `unverified` when
        the final answer doesn't survive a grounding check.

        Why this matters: the spec explicitly calls out silent-failure
        prevention. The verifier and planner can both produce a confident
        "I found X = 42" reply when in reality the page returned an error or
        the LLM hallucinated. We catch THREE patterns here:

        1. Final URL is a known auth-wall / paywall / error redirect —
           deterministic check via URL path, doesn't rely on LLM honesty.
           Fires for `success` AND `partial` (both can leave the agent on a
           blocked page).
        2. Hedging/refusal phrases — convert to status="not_found" so a
           caller can distinguish "no such data exists" from "succeeded".
        3. Numeric answers whose digits don't appear in any observed page
           text — flag as status="unverified" with a reason. This is a
           cheap deterministic check that catches the most common
           hallucination mode for finance scraping tasks.
        """
        if result.status not in ("success", "partial"):
            return

        # CHECK 1: deterministic URL-based detection of auth wall / paywall.
        # If the agent ended up on a /login, /authwall, or known anti-bot
        # redirect path, we don't trust an LLM "task complete" answer (even
        # for `partial` reaching max-steps — the redirect itself is the
        # evidence the task can't be completed).
        last_url = ""
        if result.steps:
            last_state = result.steps[-1].after_state or result.steps[-1].before_state
            if last_state:
                last_url = (last_state.url or "").lower()
        for marker in _BLOCKED_URL_MARKERS:
            if marker in last_url:
                result.status = "not_found"
                result.failure_modes.append(f"blocked_url:{marker}")
                return

        # The remaining checks only apply to `success` with a non-empty
        # answer (a `partial` result without a hedging phrase or numeric
        # claim is just an honest "I ran out of steps").
        if result.status != "success" or not result.final_answer:
            return

        answer = result.final_answer.strip()
        answer_lower = answer.lower()

        for phrase in _NOT_FOUND_PHRASES:
            if phrase in answer_lower:
                result.status = "not_found"
                result.failure_modes.append("hedged_answer")
                return

        # Collect text observed during the run for grounding.
        observed_blobs: list[str] = []
        for step in result.steps:
            for state in (step.before_state, step.after_state):
                if state and state.visible_text_summary:
                    observed_blobs.append(state.visible_text_summary)
        observed = "\n".join(observed_blobs)

        # Pull every number-ish token out of the answer that is at least 2
        # digits (so we don't false-fire on "1 result"). If the answer cites
        # a number that doesn't appear anywhere on observed pages, the agent
        # very likely fabricated it.
        nums = _NUMBER_TOKEN.findall(answer)
        if nums and observed:
            normalized_observed = observed.replace(",", "")
            ungrounded = [n for n in nums if n not in observed and n.replace(",", "") not in normalized_observed]
            if ungrounded and len(ungrounded) == len(nums):
                # *Every* numeric token in the answer is missing from observed
                # text — strongly indicates fabrication.
                result.status = "unverified"
                result.failure_modes.append(f"ungrounded_numbers:{ungrounded[:3]}")

    async def _execute_step(
        self,
        page,
        action: BrowserAction,
        step_number: int,
        trace_id: str,
    ) -> StepResult:
        """
        Execute one step with observation, verification, and healing.

        This is where the Observe → Act → Verify → Heal loop happens.
        """
        step_start = time.time()
        step_result = StepResult(step_number=step_number, action=action)

        # Observe BEFORE action
        step_result.before_state = await observe(page, "")

        # Try to dismiss any popups first
        await dismiss_popups(page)

        # Execute the action
        success, locator_strategy, error = await execute_action(page, action)
        step_result.locator_strategy_used = locator_strategy

        # EXTRACT actions return success=True with extracted data in the
        # `error` slot using a `extract_*:` prefix (executor.py). Pull that
        # out into the structured field so reactive steps can use it.
        if (
            success
            and error
            and any(
                error.startswith(p) for p in ("extract_infobox:", "extract_table:", "extract_kv:", "extract_no_match")
            )
        ):
            step_result.extracted_data = error
            error = None  # don't surface as an error

        if not success:
            step_result.error = error

            # === HEALING LOOP (not just retry!) ===
            for heal_attempt in range(_MAX_HEAL_ATTEMPTS):
                step_result.healer_activated = True

                # Observe page state for diagnosis
                current_state = await observe(page, self.screenshot_dir)

                # Diagnose root cause
                if heal_attempt == 0:
                    diagnosis = diagnose_deterministic(error or "", current_state, action)
                else:
                    diagnosis = await diagnose_with_llm(
                        error_message=error or "",
                        page_state=current_state,
                        action=action,
                        model_name=self.model_name,
                        user_api_key=self.user_api_key,
                        trace_id=trace_id,
                    )
                    self.llm_calls_count = getattr(self, "llm_calls_count", 0) + 1

                step_result.healer_diagnosis = diagnosis.root_cause.value
                step_result.healer_recovery = diagnosis.recovery_strategy

                if not diagnosis.should_retry:
                    step_result.error = f"{diagnosis.root_cause.value}: {diagnosis.explanation}"
                    break

                # Get alternative action
                alt_action = suggest_alternative_action(diagnosis, action, current_state)
                if alt_action:
                    # Execute recovery action
                    alt_success, alt_strat, alt_err = await execute_action(page, alt_action)
                    if alt_success:
                        # Recovery action worked — now retry original
                        await asyncio.sleep(0.5)
                        retry_success, retry_strat, retry_err = await execute_action(page, action)
                        if retry_success:
                            step_result.error = None
                            step_result.locator_strategy_used = retry_strat
                            logger.info(
                                "healer_recovered",
                                step=step_number,
                                diagnosis=diagnosis.root_cause.value,
                                attempt=heal_attempt + 1,
                            )
                            break
                        error = retry_err  # Update error for next diagnosis attempt
                    else:
                        error = alt_err

                logger.info(
                    "healer_attempt_failed",
                    step=step_number,
                    attempt=heal_attempt + 1,
                    diagnosis=diagnosis.root_cause.value,
                )

        # Wait briefly for page to settle after action
        await asyncio.sleep(0.3)

        # Observe AFTER action
        step_result.after_state = await observe(page, self.screenshot_dir)

        # Verify action success (silent failure prevention)
        if step_result.before_state and step_result.after_state and not step_result.error:
            step_result.verification = await verify_action(
                before=step_result.before_state,
                after=step_result.after_state,
                intended_action=f"{action.action_type.value}: {action.target_description}",
            )

            # If verification confidence is very low, flag it
            if step_result.verification.confidence < _VERIFICATION_THRESHOLD:
                logger.warning(
                    "low_verification_confidence",
                    step=step_number,
                    confidence=step_result.verification.confidence,
                    reason=step_result.verification.reason,
                )

        step_result.duration_ms = round((time.time() - step_start) * 1000, 1)
        return step_result
