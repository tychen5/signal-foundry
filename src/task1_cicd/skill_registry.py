"""
Skill Registry: Maps user requests to canonical skill names.

Three-tier matching strategy (cost-ascending order):
1. Exact match map  — O(1), zero cost
2. Fuzzy token overlap — O(n*m), zero cost
3. LLM disambiguation — one API call, tracked in cost_tracker

Only falls through to LLM when deterministic approaches fail.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from src.shared.cost_tracker import get_cost_tracker
from src.shared.llm_utils import coerce_message_text as _coerce_message_text
from src.shared.logger import get_logger

logger = get_logger("skill_registry")

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "cicd"

# Canonical skill names
VALID_SKILLS = {"lint-and-test", "build-and-release", "dependency-audit", "security-scan"}

# Exact-match map (handles common variants)
_EXACT_MAP: dict[str, str] = {
    "lint-and-test": "lint-and-test",
    "lint_and_test": "lint-and-test",
    "lint": "lint-and-test",
    "test": "lint-and-test",
    "lint-test": "lint-and-test",
    "build-and-release": "build-and-release",
    "build_and_release": "build-and-release",
    "release": "build-and-release",
    "build": "build-and-release",
    "dependency-audit": "dependency-audit",
    "dependency_audit": "dependency-audit",
    "dep-audit": "dependency-audit",
    "audit": "dependency-audit",
    "security-scan": "security-scan",
    "security_scan": "security-scan",
    "scan": "security-scan",
    "sast": "security-scan",
}

# Trigger phrases per skill for fuzzy matching
_TRIGGER_PHRASES: dict[str, list[str]] = {
    "lint-and-test": [
        "test this",
        "run tests",
        "check code quality",
        "lint",
        "run ci",
        "verify code",
        "check tests",
        "does it pass",
        "code quality",
        "run checks",
        "pytest",
        "ruff",
        "eslint",
        "jest",
    ],
    "build-and-release": [
        "release",
        "ship it",
        "deploy",
        "publish",
        "create release",
        "make a new version",
        "cut a release",
        "tag and release",
        "bump version",
        "new version",
        "changelog",
        "tag release",
    ],
    "dependency-audit": [
        "audit deps",
        "check vulnerabilities",
        "update packages",
        "cve check",
        "scan dependencies",
        "find outdated",
        "check for security issues in dependencies",
        "vulnerable packages",
        "outdated packages",
        "dependency vulnerabilities",
        "pip audit",
        "npm audit",
        "osv",
    ],
    "security-scan": [
        "scan for secrets",
        "sast",
        "check cves in code",
        "find leaked keys",
        "detect hardcoded passwords",
        "security audit",
        "check for sensitive data",
        "leaked tokens",
        "hardcoded secrets",
        "api keys in code",
        "bandit",
        "secret detection",
        "find passwords",
        "leaked credentials",
    ],
}


class SkillMatchError(Exception):
    """Raised when no skill can be matched with sufficient confidence."""


async def resolve_skill_name(
    raw: str,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    trace_id: str = "",
) -> tuple[str, float]:
    """
    Map a raw user input string to a canonical skill name.

    Returns: (canonical_skill_name, confidence_score)
    Raises SkillMatchError if no skill matches with confidence >= 0.5.
    """
    normalized = raw.strip().lower()

    # Tier 1: Exact match
    if normalized in _EXACT_MAP:
        skill = _EXACT_MAP[normalized]
        logger.info("skill_matched_exact", raw=raw, skill=skill)
        return skill, 1.0

    # Tier 2: Fuzzy token overlap
    result = _fuzzy_match(normalized)
    if result:
        skill, score = result
        logger.info("skill_matched_fuzzy", raw=raw, skill=skill, score=score)
        return skill, score

    # Tier 3: LLM disambiguation
    logger.info("skill_match_llm_fallback", raw=raw)
    try:
        skill, confidence, reasoning = await _llm_match(raw, model_name, user_api_key, trace_id)
    except Exception as e:
        logger.warning("llm_match_failed", error=str(e))
        raise SkillMatchError(
            f"Could not match '{raw}' to a skill. "
            f"Try: lint-and-test, build-and-release, dependency-audit, security-scan"
        ) from e

    if confidence < 0.5:
        raise SkillMatchError(
            f"Ambiguous skill request '{raw}' (best match: '{skill}' with {confidence:.0%} confidence). "
            f"Please be more specific."
        )

    return skill, confidence


def _fuzzy_match(normalized: str) -> Optional[tuple[str, float]]:
    """
    Simple token overlap scoring against trigger phrase lists.
    Returns (skill_name, score) or None if max score < 0.35.
    """
    # Tokenize input: split on spaces, dashes, underscores
    input_tokens = set(re.split(r"[\s\-_]+", normalized))
    input_tokens.discard("")

    best_skill = ""
    best_score = 0.0

    for skill, phrases in _TRIGGER_PHRASES.items():
        score = 0.0
        for phrase in phrases:
            phrase_tokens = set(re.split(r"[\s\-_]+", phrase.lower()))
            phrase_tokens.discard("")
            if not phrase_tokens:
                continue
            overlap = len(input_tokens & phrase_tokens)
            phrase_score = overlap / len(phrase_tokens)
            # Bonus for exact phrase match
            if phrase.lower() in normalized:
                phrase_score = max(phrase_score, 0.8)
            score = max(score, phrase_score)

        if score > best_score:
            best_score = score
            best_skill = skill

    if best_score >= 0.35 and best_skill:
        return best_skill, min(best_score, 0.9)  # cap at 0.9 for fuzzy
    return None


async def _llm_match(
    raw: str,
    model_name: Optional[str],
    user_api_key: Optional[str],
    trace_id: str,
) -> tuple[str, float, str]:
    """
    Use LLM to disambiguate a free-form skill request.
    Returns (skill_name, confidence, reasoning).
    """
    from src.llm_provider import get_llm

    prompt_path = PROMPT_DIR / "v1_skill_match.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Skill match prompt not found: {prompt_path}")

    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{user_input}", raw)

    resolved_model = model_name or "moonshotai/kimi-k2.6"
    try:
        llm = get_llm(
            model_name=resolved_model,
            user_openrouter_key=user_api_key,
            temperature=0.0,
            max_tokens=500,
        )

        start = time.monotonic()
        response = await llm.ainvoke(prompt)
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        raise LLMStageError(
            "Skill match LLM call failed",
            stage="skill_match",
            model_id=resolved_model,
            original=e,
        ) from e
    latency_ms = (time.monotonic() - start) * 1000

    response_text = _coerce_message_text(getattr(response, "content", response))

    # Parse JSON response
    try:
        # Handle markdown code blocks if LLM wraps in ```json
        clean = re.sub(r"```(?:json)?\s*", "", response_text).strip().rstrip("`").strip()
        data = json.loads(clean)
    except json.JSONDecodeError:
        # Try to extract JSON from the text
        m = re.search(r"\{[^{}]+\}", response_text)
        if m:
            data = json.loads(m.group(0))
        else:
            raise ValueError(f"LLM returned non-JSON response: {response_text[:200]}")

    skill = data.get("skill", "").strip()
    confidence = float(data.get("confidence", 0.5))
    reasoning = data.get("reasoning", "")

    if skill not in VALID_SKILLS:
        raise ValueError(f"LLM returned unknown skill: {skill}")

    # Track cost (approximate — actual tokens unknown without usage metadata)
    tracker = get_cost_tracker()
    tokens_in = len(prompt) // 4  # rough estimate: ~4 chars per token
    tokens_out = len(response_text) // 4
    tracker.record_call(
        model=resolved_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        task="task1_cicd",
        operation="skill_match",
        trace_id=trace_id,
    )

    logger.info("llm_skill_match", skill=skill, confidence=confidence, reasoning=reasoning)
    return skill, confidence, reasoning


async def llm_summarize(
    skill_name: str,
    result: dict,
    model_name: Optional[str],
    user_api_key: Optional[str],
    trace_id: str,
) -> str:
    """
    Use LLM to generate a 2-3 sentence human summary of a skill result.
    Called once per skill execution, always tracked in cost_tracker.
    """
    from src.llm_provider import get_llm

    prompt_path = PROMPT_DIR / "v1_result_summary.txt"
    if not prompt_path.exists():
        return f"Skill '{skill_name}' completed. See result JSON for details."

    prompt_template = prompt_path.read_text(encoding="utf-8")

    # Trim result JSON to avoid context explosion
    result_str = json.dumps(result, default=str)
    if len(result_str) > 3000:
        # Keep the most important fields
        trimmed = {k: v for k, v in result.items() if k != "content_text"}
        result_str = json.dumps(trimmed, default=str)[:3000]

    prompt = prompt_template.replace("{skill_name}", skill_name).replace("{result_json}", result_str)

    resolved_model = model_name or "moonshotai/kimi-k2.6"
    try:
        llm = get_llm(
            model_name=resolved_model,
            user_openrouter_key=user_api_key,
            temperature=0.3,
            max_tokens=400,
        )

        start = time.monotonic()
        response = await llm.ainvoke(prompt)
        latency_ms = (time.monotonic() - start) * 1000
        summary = _coerce_message_text(getattr(response, "content", response))
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        logger.warning("llm_summarize_failed", error=str(e))
        raise LLMStageError(
            "Skill result-summary LLM call failed",
            stage="result_summary",
            model_id=resolved_model,
            original=e,
        ) from e

    if not summary:
        # Thinking-mode model returned only reasoning_content with no answer
        # body — fall back to a deterministic summary so the eval check
        # `has_summary` doesn't false-fire.
        return f"Skill '{skill_name}' completed without an LLM summary; see result JSON."

    # Track cost
    tracker = get_cost_tracker()
    tokens_in = len(prompt) // 4
    tokens_out = len(summary) // 4
    tracker.record_call(
        model=resolved_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        task="task1_cicd",
        operation="result_summary",
        trace_id=trace_id,
    )

    return summary.strip()
