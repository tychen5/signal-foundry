"""
LLM Boundary Refiner for SEC 10-K Filings (Stage 2).

Only invoked for low-confidence boundaries detected by rule_parser.
Uses LLM with ±500 char context window around uncertain boundaries.
Cost-aware: uses cheaper model first, only escalates when needed.

Prompts are loaded from prompts/sec_extraction/ (versioned files).
See prompts/sec_extraction/README.md for iteration history.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm_provider import get_llm
from src.shared.cost_tracker import get_cost_tracker
from src.shared.llm_utils import coerce_message_text, extract_json_array, extract_json_object
from src.shared.logger import get_logger
from src.task3_sec.rule_parser import ItemBoundary, ParseResult
from src.task3_sec.schemas import STANDARD_10K_ITEMS

logger = get_logger("llm_refiner")
cost_tracker = get_cost_tracker()

# --- Prompt loading from versioned files ---
_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "prompts",
    "sec_extraction",
)


def _load_prompt(filename: str, fallback: str = "") -> str:
    """Load a prompt from the versioned prompts directory."""
    filepath = os.path.join(_PROMPTS_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning("prompt_file_not_found", file=filename, using="fallback")
        return fallback


def _load_versioned_prompt(stem: str) -> str:
    """Load latest prompt version (v3 → v2 → v1 fallback chain)."""
    for version in ("v3", "v2", "v1"):
        text = _load_prompt(f"{version}_{stem}.txt")
        if text:
            return text
    return ""


# v4 boundary-refine prompt adds edge-case hardening: combined items ("ITEMS 1 AND 2"),
# SPAC/blank-check N/A detection, early EDGAR ASCII format, going-concern false-positive
# prevention, and confidence calibration guide.
# Falls back v3 → v2 → v1 if a version is missing.
BOUNDARY_REFINE_PROMPT = _load_versioned_prompt("boundary_refine")
MISSING_ITEM_PROMPT = _load_prompt("v2_missing_item_detect.txt")


async def refine_boundaries(
    text: str,
    parse_result: ParseResult,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    confidence_threshold: float = 0.5,
    use_vision: bool = False,
    force_refine: bool = False,
    trace_id: str = "",
) -> ParseResult:
    """
    Stage 2: LLM-based boundary refinement.

    Only processes boundaries with confidence below threshold.
    Uses ±500 char context windows to minimize token usage.

    Args:
        text: Full normalized text
        parse_result: Result from rule_based_parse
        model_name: LLM model to use
        user_api_key: User's API key (optional)
        confidence_threshold: Only refine boundaries below this score
        force_refine: Refine a small set of lowest-confidence boundaries even
            when all boundaries are above the normal threshold.

    Returns:
        Updated ParseResult with refined boundaries
    """
    low_confidence = [b for b in parse_result.boundaries if b.confidence < confidence_threshold]
    if force_refine:
        try:
            forced_limit = max(1, int(os.environ.get("T3_FORCE_LLM_MAX", "3")))
        except (TypeError, ValueError):
            forced_limit = 3
        low_confidence = sorted(
            parse_result.boundaries,
            key=lambda b: (b.confidence, b.start_pos),
        )[:forced_limit]

    # If no low-confidence boundaries AND we already have a full item set,
    # skip the LLM entirely — nothing to improve.
    # But if items_found is suspiciously low (< 10), keep going so
    # _detect_missing_items can scan gaps even when the few found boundaries
    # happen to have high confidence (e.g. old-format filings where only the
    # first 3 items were detected by the rule parser).
    few_items = parse_result.items_found < 10
    if not low_confidence and not few_items:
        logger.info("no_refinement_needed", all_above_threshold=confidence_threshold)
        return parse_result

    logger.info(
        "refining_boundaries",
        total=len(parse_result.boundaries),
        low_confidence=len(low_confidence),
        threshold=confidence_threshold,
        forced=force_refine,
    )

    # Boundary refinement is a small, focused task — use a fast non-thinking
    # model. deepseek-v4-pro is excellent quality but its thinking-mode
    # responses can take 200+ seconds per call, which is unacceptable when
    # there are 15 boundaries to refine. kimi-k2.6 is fast (~3 s) and accurate
    # enough for the ±500-char heading-detection task.
    refine_model = model_name or "moonshotai/kimi-k2.6"
    # json_mode forces response_format={"type":"json_object"} on backends that
    # support it (OpenRouter VLMs, kimi-k2.6, glm-5.1, gpt-5.5). Eliminates
    # ```json fence parsing failures and prose preambles. The boundary-refine
    # prompt expects strict JSON output, so this is a pure win on supported
    # backends and silently falls back to text mode on older ones.
    try:
        llm = get_llm(
            model_name=refine_model,
            user_openrouter_key=user_api_key,
            temperature=0.0,
            json_mode=True,
        )
    except TypeError:
        # Older get_llm signature without json_mode — graceful fallback
        llm = get_llm(model_name=refine_model, user_openrouter_key=user_api_key, temperature=0.0)

    refined_boundaries = list(parse_result.boundaries)  # Copy

    # Inter-call delay to avoid 429 from NVIDIA NIM free-tier rate limit (~4 calls/min).
    # 1.5 s gap = ~40 calls/min, well under the limit.
    rate_delay_s = float(os.environ.get("LLM_REFINER_DELAY_S", "1.5"))
    consecutive_429 = 0

    # Vision support: only fires for vision-capable models AND only on the
    # FIRST few boundaries (capped via T3_VISION_MAX env). Rendering each
    # context to JPEG via headless Chromium adds ~1.5 s of latency per
    # boundary, which would dominate runtime if we did it on all 15+
    # uncertain boundaries.
    vision_renders_left = 0
    if use_vision:
        try:
            from src.task2_browser.vision import is_vision_capable
            from src.task3_sec.vision import _vision_max_renders

            if is_vision_capable(refine_model):
                vision_renders_left = _vision_max_renders()
                logger.info(
                    "t3_vision_active",
                    model=refine_model,
                    max_renders=vision_renders_left,
                )
        except Exception:
            vision_renders_left = 0

    for boundary in low_confidence:
        try:
            refined = await _refine_single_boundary(
                text,
                boundary,
                llm,
                refine_model,
                trace_id,
                use_vision=vision_renders_left > 0,
            )
            if vision_renders_left > 0:
                vision_renders_left -= 1
            if refined:
                # Replace the boundary in the list
                for i, b in enumerate(refined_boundaries):
                    if b.item_number == boundary.item_number and b.start_pos == boundary.start_pos:
                        refined_boundaries[i] = refined
                        break
            consecutive_429 = 0
        except Exception as e:
            err_str = str(e)
            logger.warning(
                "refinement_failed",
                item=boundary.item_number,
                error=err_str,
            )
            # Exponential back-off if hitting rate limits repeatedly
            if "429" in err_str or "Too Many Requests" in err_str:
                consecutive_429 += 1
                if consecutive_429 >= 3:
                    logger.warning(
                        "rate_limit_circuit_break",
                        consecutive_429=consecutive_429,
                        message="3+ consecutive 429s — abandoning further refinement",
                    )
                    break
                await asyncio.sleep(min(30.0, 5.0 * consecutive_429))
        # pace requests
        await asyncio.sleep(rate_delay_s)

    # Check for missing items
    await _detect_missing_items(text, refined_boundaries, llm, refine_model, user_api_key, trace_id)

    # Re-sort and update end positions
    refined_boundaries.sort(key=lambda b: b.start_pos)
    for i, b in enumerate(refined_boundaries):
        if i + 1 < len(refined_boundaries):
            b.end_pos = refined_boundaries[i + 1].start_pos
        else:
            b.end_pos = len(text)

    avg_conf = sum(b.confidence for b in refined_boundaries) / len(refined_boundaries) if refined_boundaries else 0.0

    return ParseResult(
        boundaries=refined_boundaries,
        part_boundaries=parse_result.part_boundaries,
        total_chars=parse_result.total_chars,
        items_found=len(refined_boundaries),
        confidence_avg=avg_conf,
    )


async def _refine_single_boundary(
    text: str,
    boundary: ItemBoundary,
    llm,
    model_name: str,
    trace_id: str,
    use_vision: bool = False,
) -> Optional[ItemBoundary]:
    """Refine a single boundary using LLM with ±500 char context.

    When `use_vision=True`, additionally render the context to a JPEG
    via headless Chromium and attach as image_url. Helps when item
    boundaries are signaled by typography (bold heading, ALL-CAPS,
    indentation) more than by literal "Item N." prose — the visual
    layout supplements the textual snippet.
    """
    # Extract context window
    ctx_start = max(0, boundary.start_pos - 200)
    ctx_end = min(len(text), boundary.start_pos + 800)
    context = text[ctx_start:ctx_end]

    start_time = time.time()

    user_text = f"Text snippet (position {ctx_start} to {ctx_end}):\n---\n{context}\n---"

    user_msg = HumanMessage(content=user_text)
    if use_vision:
        try:
            from src.task2_browser.vision import (
                make_multimodal_message_history,
            )
            from src.task3_sec.vision import render_multi_snapshots

            # Multi-snapshot: header zone (boundary itself), local context,
            # neighbor context. Each tier helps the LLM make a different
            # judgement (heading-vs-prose, status, layout).
            snapshots = await render_multi_snapshots(
                full_text=text,
                boundary_pos=boundary.start_pos,
                item_number=boundary.item_number,
            )
            if snapshots:
                user_msg = make_multimodal_message_history(user_text, snapshots)
                logger.info(
                    "t3_multi_vision_attached",
                    item=boundary.item_number,
                    snapshots=len(snapshots),
                )
        except Exception as e:
            logger.warning("t3_vision_attach_failed", error=str(e)[:120])

    messages = [
        SystemMessage(content=BOUNDARY_REFINE_PROMPT),
        user_msg,
    ]

    response = await llm.ainvoke(messages)
    latency_ms = (time.time() - start_time) * 1000

    response_text = coerce_message_text(getattr(response, "content", response))

    # Track cost
    tokens_in = len(BOUNDARY_REFINE_PROMPT + context) // 4  # Rough estimate
    tokens_out = len(response_text) // 4
    cost_tracker.record_call(
        model=model_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        task="task3_sec",
        operation="boundary_refine",
        trace_id=trace_id,
    )

    # Parse LLM response — robust extractor handles ```json fences, leading
    # prose, smart quotes, and braces nested inside string literals.
    result = extract_json_object(response_text)
    if not result:
        logger.warning("llm_parse_failed", raw=response_text[:200])
        return None

    try:
        if result.get("is_item_heading", False):
            item_number = str(result.get("item_number", boundary.item_number)).upper()
            if item_number != boundary.item_number:
                logger.warning(
                    "llm_item_number_mismatch",
                    expected=boundary.item_number,
                    actual=item_number,
                )
                item_number = boundary.item_number
            return ItemBoundary(
                item_number=item_number,
                start_pos=ctx_start + result.get("content_start_offset", boundary.start_pos - ctx_start),
                heading_text=result.get("item_title", boundary.heading_text),
                confidence=result.get("confidence", 0.8),
                source="llm_refined",
                status_hint=str(result.get("status", "")).strip(),
            )
    except (KeyError, TypeError) as e:
        logger.warning("llm_field_extract_failed", error=str(e), raw=response_text[:200])

    return None


async def _detect_missing_items(
    text: str,
    boundaries: list[ItemBoundary],
    llm,
    model_name: str,
    user_api_key: Optional[str],
    trace_id: str,
) -> None:
    """Check for items that might have been missed between known boundaries."""
    # Get set of found items
    found_items = {b.item_number for b in boundaries}
    expected_items = {item["item_number"] for item in STANDARD_10K_ITEMS}
    missing = expected_items - found_items

    if not missing:
        return

    logger.info("checking_missing_items", missing=sorted(missing))

    # For each gap between found items, check if missing items fall there
    # Only check gaps where missing items are expected by number ordering
    for i in range(len(boundaries) - 1):
        curr = boundaries[i]
        next_b = boundaries[i + 1]

        # Check if any missing items should be between these two
        curr_num = curr.item_number
        next_num = next_b.item_number

        gap_text = text[curr.start_pos : next_b.start_pos]

        # Only use LLM for large gaps that might contain items
        if len(gap_text) > 2000:
            # Use a smaller context window for efficiency
            sample = gap_text[:3000]

            try:
                prompt = MISSING_ITEM_PROMPT.format(
                    prev_item=curr_num,
                    next_item=next_num,
                    text_section=sample,
                )

                start_time = time.time()
                messages = [HumanMessage(content=prompt)]
                response = await llm.ainvoke(messages)
                latency_ms = (time.time() - start_time) * 1000

                response_text = coerce_message_text(getattr(response, "content", response))
                tokens_in = len(prompt) // 4
                tokens_out = len(response_text) // 4
                cost_tracker.record_call(
                    model=model_name,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    task="task3_sec",
                    operation="missing_item_detect",
                    trace_id=trace_id,
                )

                items_found = extract_json_array(response_text)
                if isinstance(items_found, list):
                    for item in items_found:
                        new_boundary = ItemBoundary(
                            item_number=item["item_number"].upper(),
                            start_pos=curr.start_pos + item.get("offset_in_text", 0),
                            heading_text=item.get("item_title", ""),
                            confidence=item.get("confidence", 0.7),
                            source="llm_missing_detect",
                        )
                        boundaries.append(new_boundary)
            except Exception as e:
                logger.warning("missing_detect_failed", error=str(e))
