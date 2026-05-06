"""Real-network integration tests for the LLM provider factory.

These tests are gated behind the env var `RUN_LLM_INTEGRATION=1` because they
hit live NVIDIA NIM and OpenRouter endpoints — running them in CI without
opting in would burn API credits and add network flakiness to the unit suite.

Run locally with:
    RUN_LLM_INTEGRATION=1 pytest tests/test_llm_integration.py -v

What this verifies:
    - Each registry entry actually round-trips through the OpenAI-compat
      backend (the real bug I caught: the previous langchain-nvidia path
      hit AssertionError on dual-listed models, and the wrapper kwargs
      `max_tokens` vs `max_completion_tokens` mismatch silently dropped
      response budgets).
    - extra_body (NIM thinking-mode toggles) reaches the API.
    - Both providers can be reached with their respective API keys.
"""

from __future__ import annotations

import os

import pytest

RUN = os.environ.get("RUN_LLM_INTEGRATION", "").lower() in {"1", "true", "yes"}
pytestmark = pytest.mark.skipif(
    not RUN,
    reason="Set RUN_LLM_INTEGRATION=1 to exercise live NVIDIA/OpenRouter calls.",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_id,max_tokens",
    [
        ("moonshotai/kimi-k2.6", 128),
        ("deepseek-ai/deepseek-v4-pro", 256),
        ("minimaxai/minimax-m2.7", 128),
    ],
)
async def test_nvidia_nim_round_trip(model_id: str, max_tokens: int) -> None:
    """Each registered NVIDIA NIM model returns non-empty content for a
    trivially-short prompt within a tight token budget. This catches:
      - max_tokens kwarg silently dropped (would yield 0-char content)
      - extra_body thinking toggle producing only reasoning, no answer
      - registry IDs drifting from what NVIDIA actually serves
    """
    from src.llm_provider import get_llm

    if not os.environ.get("NVIDIA_API_KEY"):
        pytest.skip("NVIDIA_API_KEY not set")

    llm = get_llm(model_name=model_id, max_tokens=max_tokens, temperature=0.0)
    response = await llm.ainvoke("Reply with the single word OK and nothing else.")
    text = (getattr(response, "content", None) or str(response)).strip()
    assert text, f"{model_id} returned empty content (likely max_tokens too low or thinking-only response)"
    assert len(text) < 200, f"{model_id} returned suspiciously long output: {text!r}"


@pytest.mark.asyncio
async def test_openrouter_round_trip() -> None:
    """OpenRouter via the same OpenAI-compat path."""
    from src.llm_provider import get_llm

    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")

    llm = get_llm(model_name="openai/gpt-5.5", max_tokens=64, temperature=0.0)
    response = await llm.ainvoke("Reply with the single word OK and nothing else.")
    text = (getattr(response, "content", None) or str(response)).strip()
    assert text


@pytest.mark.asyncio
async def test_skill_registry_llm_match_returns_canonical_skill() -> None:
    """End-to-end: a free-form request that bypasses both exact and fuzzy
    matching falls through to the LLM disambiguator and returns one of the
    four canonical skill names with confidence ≥ 0.5. Catches regressions
    in the skill_registry.llm_summarize / get_llm wiring (the bug I fixed:
    the registry was passing a ModelSelectionRequest object where get_llm
    expected a model_name string)."""
    from src.task1_cicd.skill_registry import VALID_SKILLS, resolve_skill_name

    if not os.environ.get("NVIDIA_API_KEY"):
        pytest.skip("NVIDIA_API_KEY not set")

    skill, confidence = await resolve_skill_name(
        raw="please make sure no API tokens are committed in the source tree",
        model_name="moonshotai/kimi-k2.6",
        trace_id="test-llm-integration",
    )
    assert skill in VALID_SKILLS
    assert confidence >= 0.5
