"""
Unit and integration tests for Task 2: Browser Automation Agent.

Tests cover schemas, observer, executor, healer, planner, and agent integration.
"""

from __future__ import annotations

import pytest

from src.task2_browser.schemas import (
    ActionType,
    AgentResult,
    BrowserAction,
    Diagnosis,
    FailureRootCause,
    LocatorStrategy,
    PageState,
    StepResult,
    TaskPlan,
    VerificationResult,
)

# ==============================================================================
# Schema Tests
# ==============================================================================


class TestSchemas:
    """Test Pydantic model creation and validation."""

    def test_action_type_enum_coverage(self) -> None:
        """All expected action types are defined."""
        expected = {
            "navigate",
            "click",
            "fill",
            "select",
            "scroll",
            "wait",
            "extract",
            "screenshot",
            "key_press",
            "hover",
            "done",
        }
        actual = {at.value for at in ActionType}
        assert expected == actual

    def test_failure_root_cause_taxonomy(self) -> None:
        """Root cause taxonomy covers all documented categories."""
        expected = {
            "selector_changed",
            "page_not_loaded",
            "wrong_page",
            "element_hidden",
            "element_not_found",
            "network_error",
            "captcha_detected",
            "unexpected_popup",
            "timeout",
            "unknown",
        }
        actual = {frc.value for frc in FailureRootCause}
        assert expected == actual

    def test_locator_strategy_layers(self) -> None:
        """All 3 locator layers plus sub-layers are defined."""
        strategies = {ls.value for ls in LocatorStrategy}
        assert "accessibility" in strategies  # Layer 1
        assert "semantic_dom" in strategies  # Layer 2
        assert "text_content" in strategies  # Layer 2b
        assert "css_selector" in strategies  # Layer 3
        assert "coordinate" in strategies  # Layer 3b

    def test_browser_action_creation(self) -> None:
        """BrowserAction model can be created with semantic description."""
        action = BrowserAction(
            action_type=ActionType.CLICK,
            target_description="Submit button",
            reasoning="Submit the form",
            success_criteria="Form submitted, confirmation page shown",
        )
        assert action.action_type == ActionType.CLICK
        assert action.target_description == "Submit button"
        assert action.selector == ""  # No CSS selector — AOM-first

    def test_page_state_creation(self) -> None:
        """PageState captures accessibility tree and error indicators."""
        state = PageState(
            url="https://example.com",
            title="Example",
            accessibility_tree='[button] "Submit"\n[textbox] "Search"',
            visible_text_summary="Welcome to Example",
            has_buttons=True,
            has_input_fields=True,
            error_indicators=["Form validation failed"],
        )
        assert state.has_buttons is True
        assert len(state.error_indicators) == 1

    def test_verification_result_confidence_bounds(self) -> None:
        """Confidence score is bounded 0-1."""
        vr = VerificationResult(success=True, confidence=0.9)
        assert 0.0 <= vr.confidence <= 1.0

    def test_step_result_with_healing(self) -> None:
        """StepResult tracks healer activation and diagnosis."""
        step = StepResult(
            step_number=1,
            action=BrowserAction(action_type=ActionType.CLICK, target_description="button"),
            healer_activated=True,
            healer_diagnosis="element_hidden",
            healer_recovery="Scroll to element",
        )
        assert step.healer_activated is True
        assert step.healer_diagnosis == "element_hidden"

    def test_agent_result_tracking(self) -> None:
        """AgentResult tracks self-corrections and failure modes."""
        result = AgentResult(
            status="partial",
            total_steps=5,
            self_corrections=2,
            healer_activations=3,
            failure_modes=["selector_changed", "unexpected_popup"],
        )
        assert result.self_corrections == 2
        assert len(result.failure_modes) == 2

    def test_task_plan_creation(self) -> None:
        """TaskPlan holds ordered steps with predicted failures."""
        plan = TaskPlan(
            original_task="Search Wikipedia for AI",
            steps=[
                BrowserAction(action_type=ActionType.NAVIGATE, value="https://wikipedia.org"),
                BrowserAction(action_type=ActionType.FILL, target_description="search box", value="AI"),
            ],
            predicted_failure_points=["search box may have different placeholder"],
        )
        assert len(plan.steps) == 2
        assert len(plan.predicted_failure_points) == 1

    def test_diagnosis_model(self) -> None:
        """Diagnosis classifies root cause with recovery strategy."""
        diag = Diagnosis(
            root_cause=FailureRootCause.UNEXPECTED_POPUP,
            explanation="Cookie consent dialog blocking interaction",
            recovery_strategy="Dismiss cookie banner by clicking Accept",
            should_retry=True,
            confidence=0.8,
        )
        assert diag.root_cause == FailureRootCause.UNEXPECTED_POPUP
        assert diag.should_retry is True


# ==============================================================================
# Observer Tests
# ==============================================================================


class TestObserver:
    """Test observer state capture and verification logic."""

    def test_format_a11y_tree_filters_noise(self) -> None:
        """Accessibility tree formatter filters non-interactive nodes."""
        from src.task2_browser.observer import _format_a11y_tree

        tree = {
            "role": "WebArea",
            "name": "Test Page",
            "children": [
                {"role": "heading", "name": "Welcome"},
                {"role": "button", "name": "Click Me"},
                {"role": "textbox", "name": "Search"},
                {"role": "generic", "name": ""},  # Should be filtered
            ],
        }
        result = _format_a11y_tree(tree)
        assert "button" in result.lower()
        assert "Click Me" in result
        assert "Search" in result

    def test_summarize_text_truncation(self) -> None:
        """Text summary truncates long text while preserving start and end."""
        from src.task2_browser.observer import _summarize_text

        long_text = "A" * 5000
        result = _summarize_text(long_text)
        assert len(result) < 5000
        assert "..." in result

    def test_summarize_text_short_passthrough(self) -> None:
        """Short text passes through unchanged."""
        from src.task2_browser.observer import _summarize_text

        short = "Hello world"
        assert _summarize_text(short) == short

    @pytest.mark.asyncio
    async def test_verify_action_navigate_url_changed(self) -> None:
        """Navigation verification checks URL change."""
        from src.task2_browser.observer import verify_action

        before = PageState(url="https://google.com", title="Google")
        after = PageState(url="https://google.com/search?q=test", title="test - Google Search")

        result = await verify_action(before, after, "navigate to search results")
        assert result.success is True
        assert result.url_changed is True
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_verify_action_detects_new_errors(self) -> None:
        """Verification catches new error indicators (silent failure prevention)."""
        from src.task2_browser.observer import verify_action

        before = PageState(url="https://example.com", error_indicators=[])
        after = PageState(url="https://example.com", error_indicators=["Form validation failed"])

        result = await verify_action(before, after, "click submit button")
        assert result.success is False
        assert result.confidence < 0.5
        assert "error" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_verify_action_fill_always_succeeds(self) -> None:
        """Fill action verification is lenient (DOM may not visibly change)."""
        from src.task2_browser.observer import verify_action

        before = PageState(url="https://example.com")
        after = PageState(url="https://example.com")

        result = await verify_action(before, after, "fill the search input")
        assert result.success is True


# ==============================================================================
# Healer Tests
# ==============================================================================


class TestHealer:
    """Test self-healing diagnosis and recovery suggestions."""

    def test_diagnose_timeout_as_element_not_found(self) -> None:
        """Timeout with 'locator' keyword → element_not_found."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(url="https://example.com")
        action = BrowserAction(action_type=ActionType.CLICK, target_description="Submit")

        diag = diagnose_deterministic(
            "Timeout 8000ms exceeded waiting for locator",
            state,
            action,
        )
        assert diag.root_cause == FailureRootCause.ELEMENT_NOT_FOUND
        assert diag.should_retry is True

    def test_diagnose_network_error(self) -> None:
        """Network errors correctly classified."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(url="about:blank")
        action = BrowserAction(action_type=ActionType.NAVIGATE, value="https://example.com")

        diag = diagnose_deterministic("net::ERR_NAME_NOT_RESOLVED", state, action)
        assert diag.root_cause == FailureRootCause.NETWORK_ERROR

    def test_diagnose_hidden_element_with_popup(self) -> None:
        """Hidden element with cookie text → unexpected_popup."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(
            url="https://news.com",
            visible_text_summary="This site uses cookies... Accept All",
            error_indicators=["Cookie consent required"],
        )
        action = BrowserAction(action_type=ActionType.CLICK, target_description="headline")

        diag = diagnose_deterministic("Element is not visible", state, action)
        assert diag.root_cause == FailureRootCause.UNEXPECTED_POPUP

    def test_diagnose_captcha(self) -> None:
        """CAPTCHA detection stops retrying."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(
            url="https://example.com",
            visible_text_summary="Please complete the CAPTCHA to continue",
        )
        action = BrowserAction(action_type=ActionType.CLICK, target_description="button")

        diag = diagnose_deterministic("captcha verification required", state, action)
        assert diag.root_cause == FailureRootCause.CAPTCHA_DETECTED
        assert diag.should_retry is False

    def test_diagnose_page_not_loaded(self) -> None:
        """Blank page → page_not_loaded."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(url="", title="")
        action = BrowserAction(action_type=ActionType.CLICK, target_description="button")

        diag = diagnose_deterministic("Element not found", state, action)
        assert diag.root_cause == FailureRootCause.PAGE_NOT_LOADED

    def test_suggest_alternative_popup_dismiss(self) -> None:
        """Popup diagnosis → suggest dismissing popup."""
        from src.task2_browser.healer import suggest_alternative_action

        diag = Diagnosis(root_cause=FailureRootCause.UNEXPECTED_POPUP)
        action = BrowserAction(action_type=ActionType.CLICK, target_description="headline")
        state = PageState()

        alt = suggest_alternative_action(diag, action, state)
        assert alt is not None
        assert alt.action_type == ActionType.CLICK
        assert "dismiss" in alt.target_description.lower() or "close" in alt.target_description.lower()

    def test_suggest_alternative_scroll_for_hidden(self) -> None:
        """Hidden element → suggest scrolling."""
        from src.task2_browser.healer import suggest_alternative_action

        diag = Diagnosis(root_cause=FailureRootCause.ELEMENT_HIDDEN)
        action = BrowserAction(action_type=ActionType.CLICK, target_description="footer link")
        state = PageState()

        alt = suggest_alternative_action(diag, action, state)
        assert alt is not None
        assert alt.action_type == ActionType.SCROLL

    def test_suggest_alternative_wait_for_not_loaded(self) -> None:
        """Page not loaded → suggest waiting."""
        from src.task2_browser.healer import suggest_alternative_action

        diag = Diagnosis(root_cause=FailureRootCause.PAGE_NOT_LOADED)
        action = BrowserAction(action_type=ActionType.CLICK, target_description="button")
        state = PageState()

        alt = suggest_alternative_action(diag, action, state)
        assert alt is not None
        assert alt.action_type == ActionType.WAIT

    def test_suggest_alternative_back_for_wrong_page(self) -> None:
        """Wrong page → suggest navigating back."""
        from src.task2_browser.healer import suggest_alternative_action

        diag = Diagnosis(root_cause=FailureRootCause.WRONG_PAGE)
        action = BrowserAction(action_type=ActionType.CLICK, target_description="button")
        state = PageState()

        alt = suggest_alternative_action(diag, action, state)
        assert alt is not None
        assert alt.action_type == ActionType.NAVIGATE

    def test_no_retry_for_captcha(self) -> None:
        """CAPTCHA → no alternative action (cannot solve)."""
        from src.task2_browser.healer import suggest_alternative_action

        diag = Diagnosis(root_cause=FailureRootCause.CAPTCHA_DETECTED, should_retry=False)
        action = BrowserAction(action_type=ActionType.CLICK, target_description="button")
        state = PageState()

        alt = suggest_alternative_action(diag, action, state)
        # CAPTCHA is not in the mapping, so None is returned
        assert alt is None

    def test_diagnose_rate_limit_429(self) -> None:
        """429/Too Many Requests → recoverable network error with backoff."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(url="https://example.com")
        action = BrowserAction(action_type=ActionType.NAVIGATE, target_description="page")

        diag = diagnose_deterministic("HTTP 429 Too Many Requests", state, action)
        assert diag.root_cause == FailureRootCause.NETWORK_ERROR
        assert diag.should_retry is True
        assert "back off" in diag.recovery_strategy.lower()

    def test_diagnose_403_blocked(self) -> None:
        """403/Forbidden → anti-bot block, do NOT retry."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(url="https://example.com")
        action = BrowserAction(action_type=ActionType.NAVIGATE, target_description="page")

        diag = diagnose_deterministic("HTTP 403 Forbidden", state, action)
        assert diag.root_cause == FailureRootCause.CAPTCHA_DETECTED
        assert diag.should_retry is False

    def test_diagnose_frame_detached(self) -> None:
        """Frame detached mid-action → page_not_loaded, retry against fresh DOM."""
        from src.task2_browser.healer import diagnose_deterministic

        state = PageState(url="https://example.com/destination")
        action = BrowserAction(action_type=ActionType.CLICK, target_description="button")

        diag = diagnose_deterministic("frame was detached", state, action)
        assert diag.root_cause == FailureRootCause.PAGE_NOT_LOADED
        assert diag.should_retry is True


# ==============================================================================
# Silent-Failure Guard Tests
# ==============================================================================


class TestSilentFailureGuard:
    """Verify the agent downgrades plausible-but-wrong final answers."""

    def _make_agent(self):
        from src.task2_browser.agent import BrowserAgent

        return BrowserAgent()

    def _make_result(self, answer: str, observed_text: str = "") -> "AgentResult":
        from src.task2_browser.schemas import AgentResult, StepResult

        result = AgentResult(
            trace_id="t",
            task_description="test",
            target_url="https://example.com",
            status="success",
            final_answer=answer,
        )
        if observed_text:
            step = StepResult(
                step_number=1,
                action=BrowserAction(action_type=ActionType.NAVIGATE, target_description="x"),
                after_state=PageState(url="https://example.com", visible_text_summary=observed_text),
            )
            result.steps.append(step)
        return result

    def test_hedged_answer_marked_not_found(self) -> None:
        agent = self._make_agent()
        result = self._make_result("I cannot find that information on this page.")
        agent._guard_against_silent_success(result)
        assert result.status == "not_found"
        assert "hedged_answer" in result.failure_modes

    def test_chinese_hedge_phrase_marked_not_found(self) -> None:
        agent = self._make_agent()
        result = self._make_result("頁面沒有相關資訊，無法取得指定的數值。")
        agent._guard_against_silent_success(result)
        assert result.status == "not_found"

    def test_ungrounded_numbers_marked_unverified(self) -> None:
        """If the answer cites numbers that don't appear anywhere in observed
        page text, mark unverified — likely fabrication."""
        agent = self._make_agent()
        result = self._make_result(
            answer="The TX support is at 22850 and resistance is at 23420.",
            observed_text="Welcome to example.com — this domain is for use in illustrative examples in documents.",
        )
        agent._guard_against_silent_success(result)
        assert result.status == "unverified"
        assert any("ungrounded_numbers" in fm for fm in result.failure_modes)

    def test_grounded_numbers_pass_through(self) -> None:
        agent = self._make_agent()
        result = self._make_result(
            answer="The TX support is at 22850 and resistance is at 23420.",
            observed_text="盤後支撐 22850 / 壓力 23420 來源 玩股網",
        )
        agent._guard_against_silent_success(result)
        assert result.status == "success"
        assert result.failure_modes == []

    def test_no_observed_text_does_not_falsely_unverify(self) -> None:
        """When the run produced no observed text (e.g. failure before any
        navigation), don't penalise an answer just because grounding is
        impossible — only the hedge check applies."""
        agent = self._make_agent()
        result = self._make_result("The CIK is 320193.", observed_text="")
        agent._guard_against_silent_success(result)
        assert result.status == "success"


# ==============================================================================
# Planner Tests
# ==============================================================================


class TestPlanner:
    """Test plan parsing and action mapping."""

    def test_map_action_type_common_verbs(self) -> None:
        """Action type mapping covers common verbs."""
        from src.task2_browser.planner import _map_action_type

        assert _map_action_type("navigate") == ActionType.NAVIGATE
        assert _map_action_type("goto") == ActionType.NAVIGATE
        assert _map_action_type("click") == ActionType.CLICK
        assert _map_action_type("fill") == ActionType.FILL
        assert _map_action_type("type") == ActionType.FILL
        assert _map_action_type("select") == ActionType.SELECT
        assert _map_action_type("scroll") == ActionType.SCROLL
        assert _map_action_type("wait") == ActionType.WAIT
        assert _map_action_type("extract") == ActionType.EXTRACT
        assert _map_action_type("done") == ActionType.DONE
        assert _map_action_type("complete") == ActionType.DONE

    def test_parse_plan_from_json(self) -> None:
        """Plan parser extracts steps from JSON response."""
        from src.task2_browser.planner import _parse_plan

        response = """Here is the plan:
[
  {"action": "navigate", "target": "Wikipedia", "value": "https://wikipedia.org", "reasoning": "Go to start"},
  {"action": "fill", "target": "search box", "value": "AI", "reasoning": "Enter query"},
  {"action": "key_press", "target": "search", "value": "Enter", "reasoning": "Submit"},
  {"action": "extract", "target": "article", "value": "", "reasoning": "Get content"}
]"""
        plan = _parse_plan(response, "Search Wikipedia", None)
        assert len(plan.steps) == 4
        assert plan.steps[0].action_type == ActionType.NAVIGATE
        assert plan.steps[1].action_type == ActionType.FILL

    def test_parse_plan_fallback_numbered_list(self) -> None:
        """Plan parser falls back to numbered list parsing."""
        from src.task2_browser.planner import _parse_plan

        response = """Steps:
1. Navigate to the website
2. Click the search button
3. Type the query"""
        plan = _parse_plan(response, "Search something", "https://example.com")
        assert len(plan.steps) >= 3  # 3 parsed + 1 prepended navigation

    def test_create_fallback_plan_with_url(self) -> None:
        """Fallback plan includes navigation step when URL provided."""
        from src.task2_browser.planner import _create_fallback_plan

        plan = _create_fallback_plan("Do something", "https://example.com")
        assert len(plan.steps) == 1
        assert plan.steps[0].action_type == ActionType.NAVIGATE
        assert plan.steps[0].value == "https://example.com"

    def test_parse_action_done_detection(self) -> None:
        """Action parser detects task completion."""
        from src.task2_browser.planner import _parse_action

        action = _parse_action("The task is done. The answer is: 42")
        assert action.action_type == ActionType.DONE

    def test_parse_action_json(self) -> None:
        """Action parser handles JSON response."""
        from src.task2_browser.planner import _parse_action

        response = '{"action": "click", "target": "Submit button", "value": "", "reasoning": "Submit form"}'
        action = _parse_action(response)
        assert action.action_type == ActionType.CLICK
        assert action.target_description == "Submit button"

    def test_parse_verification_complete(self) -> None:
        """Verification parser detects completion."""
        from src.task2_browser.planner import _parse_verification

        complete, answer, conf = _parse_verification(
            '{"complete": true, "answer": "The top 3 results are...", "confidence": 0.9}'
        )
        assert complete is True
        assert "results" in answer
        assert conf == 0.9

    def test_parse_verification_incomplete(self) -> None:
        """Verification parser detects incomplete state."""
        from src.task2_browser.planner import _parse_verification

        complete, _, conf = _parse_verification("No, the task is not complete yet.")
        assert complete is False
        assert conf < 0.5


# ==============================================================================
# Prompt Files
# ==============================================================================


class TestPromptFiles:
    """Verify prompt files exist and are non-empty."""

    def test_planner_prompt_exists(self) -> None:
        """Planner prompt file exists and is non-empty."""
        from src.task2_browser.planner import PLANNER_PROMPT

        assert PLANNER_PROMPT
        assert "action" in PLANNER_PROMPT.lower()

    def test_actor_prompt_exists(self) -> None:
        """Actor prompt file exists and is non-empty."""
        from src.task2_browser.planner import ACTOR_PROMPT

        assert ACTOR_PROMPT
        assert "action" in ACTOR_PROMPT.lower()

    def test_verifier_prompt_exists(self) -> None:
        """Verifier prompt file exists and is non-empty."""
        from src.task2_browser.planner import VERIFIER_PROMPT

        assert VERIFIER_PROMPT
        assert "complete" in VERIFIER_PROMPT.lower()

    def test_healer_prompt_exists(self) -> None:
        """Healer prompt file exists and is non-empty."""
        from src.task2_browser.healer import HEALER_PROMPT

        assert HEALER_PROMPT
        assert "root cause" in HEALER_PROMPT.lower()


# ==============================================================================
# Eval Set Validation
# ==============================================================================


class TestEvalSet:
    """Verify eval set structure and coverage."""

    def test_eval_set_loads(self) -> None:
        """Eval set JSON loads successfully."""
        import json
        from pathlib import Path

        eval_path = Path(__file__).parent.parent / "evals" / "task2" / "eval_set.json"
        cases = json.loads(eval_path.read_text())
        assert len(cases) >= 8

    def test_eval_set_has_required_fields(self) -> None:
        """Each case has required fields."""
        import json
        from pathlib import Path

        eval_path = Path(__file__).parent.parent / "evals" / "task2" / "eval_set.json"
        cases = json.loads(eval_path.read_text())

        for case in cases:
            assert "case_id" in case
            assert "task" in case
            assert "input_data" in case
            assert "task_description" in case["input_data"]

    def test_eval_set_covers_difficulty_levels(self) -> None:
        """Eval set includes easy, normal, and hard/edge cases."""
        import json
        from pathlib import Path

        eval_path = Path(__file__).parent.parent / "evals" / "task2" / "eval_set.json"
        cases = json.loads(eval_path.read_text())

        difficulties = {c.get("difficulty", "normal") for c in cases}
        assert "easy" in difficulties or "normal" in difficulties
        assert "hard" in difficulties or "edge_case" in difficulties

    def test_eval_set_covers_task_types(self) -> None:
        """Eval set covers multiple task types (search, form, navigation, etc)."""
        import json
        from pathlib import Path

        eval_path = Path(__file__).parent.parent / "evals" / "task2" / "eval_set.json"
        cases = json.loads(eval_path.read_text())

        all_tags = set()
        for case in cases:
            all_tags.update(case.get("tags", []))

        assert "search" in all_tags
        assert "form" in all_tags or "fill" in all_tags
        assert "navigation" in all_tags or "multi_step" in all_tags


# ==============================================================================
# Regression Tests — bugs found by running the live path
# ==============================================================================


class TestRegressions:
    """Regression tests for bugs that only surfaced during live runs."""

    def test_observer_does_not_use_removed_page_accessibility(self) -> None:
        """observer.observe() must not reference page.accessibility (removed in Playwright ≥1.46)."""
        import inspect

        from src.task2_browser import observer

        source = inspect.getsource(observer.observe)
        assert "page.accessibility" not in source, (
            "page.accessibility was removed in Playwright ≥1.46 — use page.locator('body').aria_snapshot()"
        )
        assert "aria_snapshot" in source, "observe() should use locator.aria_snapshot()"

    def test_cost_tracker_record_call_has_latency_and_operation(self) -> None:
        """All record_call() call sites in planner.py must pass latency_ms and operation."""
        import inspect

        from src.task2_browser import planner

        source = inspect.getsource(planner)
        # Verify all record_call sites include required keyword args
        assert "latency_ms=" in source, "planner.py record_call() missing latency_ms="
        assert "operation=" in source, "planner.py record_call() missing operation="
        # Verify old wrong task labels are gone
        assert "browser_planner" not in source, "task= should be 'task2_browser', not 'browser_planner'"
        assert "browser_actor" not in source, "task= should be 'task2_browser', not 'browser_actor'"
        assert "browser_verifier" not in source, "task= should be 'task2_browser', not 'browser_verifier'"

    def test_healer_record_call_has_latency_and_operation(self) -> None:
        """healer.py record_call() must pass latency_ms and operation."""
        import inspect

        from src.task2_browser import healer

        source = inspect.getsource(healer)
        assert "latency_ms=" in source, "healer.py record_call() missing latency_ms="
        assert "operation=" in source, "healer.py record_call() missing operation="
        assert "browser_healer" not in source, "task= should be 'task2_browser', not 'browser_healer'"

    def test_cost_tracker_record_call_signature(self) -> None:
        """CostTracker.record_call requires latency_ms and operation (not optional)."""
        import inspect

        from src.shared.cost_tracker import CostTracker

        sig = inspect.signature(CostTracker.record_call)
        params = list(sig.parameters.keys())
        assert "latency_ms" in params, "CostTracker.record_call missing latency_ms param"
        assert "operation" in params, "CostTracker.record_call missing operation param"
        # Both should be required (no default value)
        assert sig.parameters["latency_ms"].default is inspect.Parameter.empty
        assert sig.parameters["operation"].default is inspect.Parameter.empty
