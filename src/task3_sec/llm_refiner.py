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
# v5 anchor-aware gap-fill: single LLM call with all known anchors + all
# missing items + gap excerpts. Designed for Citi/Intel-style filings
# where the rule parser found only 3-4 anchors but 18+ items remain
# missing. Replaces the per-boundary refine loop for catastrophic cases.
ANCHOR_GAP_FILL_PROMPT = _load_prompt("v5_anchor_aware_gap_fill.txt")
# v6 full-doc extraction: when the entire normalized doc fits in
# Gemini-3.1-Pro's 1M-token context (~1.4 MB chars), prefer to send the
# WHOLE document instead of head+mid+tail excerpts. Avoids losing context
# at omitted-bridge boundaries and lets the LLM use absolute positions
# directly. The prompt asks for absolute char positions in the full text.
FULL_DOC_EXTRACTION_PROMPT = _load_prompt("v6_full_doc_extraction.txt")


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
        try:
            llm = get_llm(model_name=refine_model, user_openrouter_key=user_api_key, temperature=0.0)
        except Exception as e:
            from src.shared.llm_errors import LLMStageError

            raise LLMStageError(
                "SEC boundary-refiner LLM initialization failed",
                stage="stage2.boundary_refine",
                model_id=refine_model,
                original=e,
            ) from e
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        raise LLMStageError(
            "SEC boundary-refiner LLM initialization failed",
            stage="stage2.boundary_refine",
            model_id=refine_model,
            original=e,
        ) from e

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
            from src.shared.llm_errors import LLMStageError

            if isinstance(e, LLMStageError):
                raise
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

    try:
        response = await llm.ainvoke(messages)
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        raise LLMStageError(
            "SEC boundary-refine LLM call failed",
            stage=f"stage2.boundary_refine.item_{boundary.item_number}",
            model_id=model_name,
            original=e,
        ) from e
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
                try:
                    response = await llm.ainvoke(messages)
                except Exception as e:
                    from src.shared.llm_errors import LLMStageError

                    raise LLMStageError(
                        "SEC missing-item LLM call failed",
                        stage="stage2.missing_item_detect",
                        model_id=model_name,
                        original=e,
                    ) from e
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
                from src.shared.llm_errors import LLMStageError

                if isinstance(e, LLMStageError):
                    raise
                logger.warning("missing_detect_failed", error=str(e))


# ============================================================================
# v5 anchor-aware gap-fill (single-call replacement for the per-boundary loop)
# ============================================================================

# Max chars per gap excerpt sent to the LLM. Anchors are usually distributed
# across the doc, so a 1.18 MB Citi document with 5 anchors yields gaps
# averaging ~240k chars each — too big for any model context. We sample
# the gap in chunks, prioritizing the START (where headings live) and
# spread of middle (in case the heading is mid-gap).
_GAP_EXCERPT_HEAD_CHARS = 30_000
_GAP_EXCERPT_MID_CHARS = 15_000
_GAP_EXCERPT_TAIL_CHARS = 8_000

# When the entire normalized doc fits in budget, prefer FULL-DOC mode
# over gap-excerpting — gives the LLM total scope to find missing items
# without losing context to omitted-bridge markers. Gemini 3.1 Pro has
# 1M token context, so up to ~3M chars fit easily.
_FULL_DOC_BUDGET_CHARS = 1_400_000


def _build_gap_excerpts(
    text: str,
    anchors: list[ItemBoundary],
) -> list[dict]:
    """Build text excerpts covering the gaps between anchors.

    For each consecutive pair of anchors (plus doc-start→first and
    last→doc-end), produce an excerpt containing:
      - first `_GAP_EXCERPT_HEAD_CHARS` chars of the gap (where new
        headings usually appear right after a preceding section ends)
      - `_GAP_EXCERPT_MID_CHARS` from the middle (for long gaps)
      - last `_GAP_EXCERPT_TAIL_CHARS` chars (for headings that appear
        at the end of a section's content)

    Returns:
        List of {"gap_id": str, "prev_item": str, "next_item": str,
                 "gap_start": int, "gap_end": int, "excerpt": str}
    """
    if not anchors:
        # Single gap covering the entire body
        body_floor = int(len(text) * 0.05)
        body_ceil = int(len(text) * 0.95)
        return [{
            "gap_id": "gap_0",
            "prev_item": "START",
            "next_item": "END",
            "gap_start": body_floor,
            "gap_end": body_ceil,
            "excerpt": _excerpt_gap(text, body_floor, body_ceil),
        }]

    gaps: list[dict] = []
    sorted_anchors = sorted(anchors, key=lambda b: b.start_pos)

    # Gap 0: doc start → first anchor
    if sorted_anchors[0].start_pos > 200:
        gap_start = int(len(text) * 0.05)  # skip TOC
        gap_end = sorted_anchors[0].start_pos
        if gap_end > gap_start:
            gaps.append({
                "gap_id": "gap_0",
                "prev_item": "START",
                "next_item": sorted_anchors[0].item_number,
                "gap_start": gap_start,
                "gap_end": gap_end,
                "excerpt": _excerpt_gap(text, gap_start, gap_end),
            })

    # Gaps between consecutive anchors
    for i in range(len(sorted_anchors) - 1):
        curr = sorted_anchors[i]
        nxt = sorted_anchors[i + 1]
        gap_start = curr.start_pos + 100  # skip the anchor heading itself
        gap_end = nxt.start_pos
        if gap_end - gap_start < 500:
            continue  # too small to contain a heading
        gaps.append({
            "gap_id": f"gap_{i + 1}",
            "prev_item": curr.item_number,
            "next_item": nxt.item_number,
            "gap_start": gap_start,
            "gap_end": gap_end,
            "excerpt": _excerpt_gap(text, gap_start, gap_end),
        })

    # Final gap: last anchor → end of body
    last = sorted_anchors[-1]
    end_zone = int(len(text) * 0.92)  # skip end-index appendix
    gap_start = last.start_pos + 100
    gap_end = end_zone
    if gap_end - gap_start > 500:
        gaps.append({
            "gap_id": f"gap_{len(sorted_anchors)}",
            "prev_item": last.item_number,
            "next_item": "END",
            "gap_start": gap_start,
            "gap_end": gap_end,
            "excerpt": _excerpt_gap(text, gap_start, gap_end),
        })

    return gaps


def _excerpt_gap(text: str, start: int, end: int) -> str:
    """Build a head + mid + tail excerpt of a gap region.

    For gaps small enough to fit in our excerpt budget, return the full
    gap. For larger gaps, sample 3 windows: head (where new headings
    usually appear), middle (in case heading is mid-gap), tail.
    """
    gap_text = text[start:end]
    budget = _GAP_EXCERPT_HEAD_CHARS + _GAP_EXCERPT_MID_CHARS + _GAP_EXCERPT_TAIL_CHARS
    if len(gap_text) <= budget:
        return gap_text
    head = gap_text[:_GAP_EXCERPT_HEAD_CHARS]
    mid_start = (len(gap_text) - _GAP_EXCERPT_MID_CHARS) // 2
    mid = gap_text[mid_start:mid_start + _GAP_EXCERPT_MID_CHARS]
    tail = gap_text[-_GAP_EXCERPT_TAIL_CHARS:]
    return (
        head
        + f"\n\n[...{mid_start - _GAP_EXCERPT_HEAD_CHARS} chars omitted...]\n\n"
        + mid
        + f"\n\n[...{len(gap_text) - mid_start - _GAP_EXCERPT_MID_CHARS - _GAP_EXCERPT_TAIL_CHARS} chars omitted...]\n\n"
        + tail
    )


async def anchor_aware_gap_fill(
    text: str,
    parse_result: ParseResult,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    trace_id: str = "",
) -> ParseResult:
    """Stage 2 alternative: single-call gap-fill using anchors + missing items.

    Designed for catastrophic-coverage cases (Citi 2026 / Intel 2026)
    where the rule parser found only 3-5 anchors but 18+ items remain
    missing. The traditional `refine_boundaries` loop iterates over
    low-confidence boundaries one at a time — useless when most items
    have NO boundary at all.

    This function:
      1. Takes existing anchors as ground truth
      2. Builds gap excerpts between consecutive anchors
      3. Sends ONE LLM call with: full item list + anchors + missing
         items + all gap excerpts
      4. The LLM scans each gap for the missing items' body headings
      5. New boundaries are created from the LLM's findings

    Falls back gracefully — any LLM error returns the original parse_result
    unchanged so the pipeline can continue.

    Args:
        text: Full normalized filing text
        parse_result: Result from rule_based_parse (anchors)
        model_name: LLM model. Gemini 3.1 Pro recommended for its 1M
            context window — fits all gap excerpts in one call.
        user_api_key: User's OpenRouter key
        trace_id: For cost tracking

    Returns:
        ParseResult with gap-filled boundaries merged in.
    """
    if not ANCHOR_GAP_FILL_PROMPT:
        logger.warning("anchor_gap_fill_prompt_missing")
        return parse_result

    found_items = {b.item_number for b in parse_result.boundaries}
    expected_items = [it["item_number"] for it in STANDARD_10K_ITEMS]
    missing = [item for item in expected_items if item not in found_items]

    if not missing:
        logger.info("anchor_gap_fill_skipped_full_coverage")
        return parse_result

    # Long-context model preferred. Default to gemini-3.1-pro-preview
    # (1M context, vision-capable, strong at structured extraction).
    refine_model = model_name or "google/gemini-3.1-pro-preview"

    # Full-doc mode: when the entire normalized text fits in the model's
    # context budget AND we have the v6 prompt available, prefer to send
    # the WHOLE document. This lets the LLM see the full doc structure
    # and resolves the missing-item problem in one shot.
    full_doc_mode = bool(FULL_DOC_EXTRACTION_PROMPT) and len(text) <= _FULL_DOC_BUDGET_CHARS

    if full_doc_mode:
        return await _full_doc_extract(
            text=text,
            parse_result=parse_result,
            missing=missing,
            llm_model=refine_model,
            user_api_key=user_api_key,
            trace_id=trace_id,
        )

    gaps = _build_gap_excerpts(text, parse_result.boundaries)
    if not gaps:
        logger.info("anchor_gap_fill_skipped_no_gaps")
        return parse_result

    try:
        llm = get_llm(
            model_name=refine_model,
            user_openrouter_key=user_api_key,
            temperature=0.0,
            json_mode=True,
        )
    except TypeError:
        try:
            llm = get_llm(model_name=refine_model, user_openrouter_key=user_api_key, temperature=0.0)
        except Exception as e:
            from src.shared.llm_errors import LLMStageError

            raise LLMStageError(
                "SEC anchor-gap-fill LLM init failed",
                stage="stage2.anchor_gap_fill",
                model_id=refine_model,
                original=e,
            ) from e
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        raise LLMStageError(
            "SEC anchor-gap-fill LLM init failed",
            stage="stage2.anchor_gap_fill",
            model_id=refine_model,
            original=e,
        ) from e

    # Build the user message: items, anchors, missing, gap excerpts.
    item_lines = []
    for it in STANDARD_10K_ITEMS:
        marker = "ANCHOR" if it["item_number"] in found_items else "MISSING"
        item_lines.append(f"  [{marker}] Item {it['item_number']}: {it['item_title']}")

    anchor_lines = []
    for b in sorted(parse_result.boundaries, key=lambda x: x.start_pos):
        anchor_lines.append(f"  Item {b.item_number} @ char {b.start_pos} ({b.heading_text!r})")

    gap_blocks = []
    total_excerpt_chars = 0
    for g in gaps:
        gap_blocks.append(
            f"=== GAP ID: {g['gap_id']} ===\n"
            f"Between anchor Item {g['prev_item']} and Item {g['next_item']}\n"
            f"Char range in document: [{g['gap_start']}, {g['gap_end']}]\n"
            f"Excerpt:\n{g['excerpt']}\n"
            f"=== END {g['gap_id']} ===\n"
        )
        total_excerpt_chars += len(g["excerpt"])

    user_text = (
        "STANDARD 10-K ITEMS (with anchor status):\n"
        + "\n".join(item_lines)
        + "\n\nKNOWN ANCHORS (rule-parser found these):\n"
        + ("\n".join(anchor_lines) or "  (no anchors found yet)")
        + f"\n\nMISSING ITEMS YOU MUST LOCATE: {missing}\n\n"
        + "GAP EXCERPTS (search these for missing item headings):\n\n"
        + "\n".join(gap_blocks)
        + "\n\nReturn a JSON ARRAY with one object per MISSING item. "
        + "Use offset_in_gap relative to the start of the gap excerpt you found it in."
    )

    logger.info(
        "anchor_gap_fill_invoking",
        anchors=len(parse_result.boundaries),
        missing=len(missing),
        gaps=len(gaps),
        total_excerpt_chars=total_excerpt_chars,
        model=refine_model,
    )

    start_time = time.time()
    messages = [
        SystemMessage(content=ANCHOR_GAP_FILL_PROMPT),
        HumanMessage(content=user_text),
    ]
    try:
        response = await llm.ainvoke(messages)
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        if isinstance(e, LLMStageError):
            raise
        logger.warning("anchor_gap_fill_llm_call_failed", err=str(e)[:200])
        # Soft-fail — return original parse_result so pipeline continues
        return parse_result

    latency_ms = (time.time() - start_time) * 1000
    response_text = coerce_message_text(getattr(response, "content", response))

    tokens_in = len(ANCHOR_GAP_FILL_PROMPT + user_text) // 4
    tokens_out = len(response_text) // 4
    cost_tracker.record_call(
        model=refine_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        task="task3_sec",
        operation="anchor_gap_fill",
        trace_id=trace_id,
    )

    results = extract_json_array(response_text)
    if not isinstance(results, list):
        # Try object-wrapped form
        obj = extract_json_object(response_text)
        if isinstance(obj, dict):
            for key in ("items", "results", "missing", "found_items"):
                if isinstance(obj.get(key), list):
                    results = obj[key]
                    break
    if not isinstance(results, list):
        logger.warning("anchor_gap_fill_parse_failed", raw=response_text[:200])
        return parse_result

    # Build a gap-id → gap dict for offset translation
    gap_index = {g["gap_id"]: g for g in gaps}

    new_boundaries = list(parse_result.boundaries)
    added = 0
    for entry in results:
        if not isinstance(entry, dict):
            continue
        item_number = str(entry.get("item_number", "")).upper().strip()
        if not item_number or item_number not in missing:
            continue
        found = bool(entry.get("found", False))
        if not found:
            continue
        gap_id = entry.get("gap_id")
        offset_in_gap = entry.get("offset_in_gap")
        gap = gap_index.get(gap_id) if isinstance(gap_id, str) else None
        if not gap or not isinstance(offset_in_gap, (int, float)):
            continue
        # Translate gap-relative offset → absolute char position in `text`.
        # The excerpt may have "[...N chars omitted...]" gaps if the
        # original gap was larger than the excerpt budget. Use the
        # excerpt-text to find where the heading is, then map back to
        # the absolute position.
        excerpt = gap["excerpt"]
        if 0 <= offset_in_gap < len(excerpt):
            heading_text_str = entry.get("heading_text") or ""
            # If the model gave a heading text, prefer to locate it
            # exactly inside the excerpt (handles "omitted" gaps).
            if heading_text_str:
                idx_in_excerpt = excerpt.find(heading_text_str)
                if idx_in_excerpt == -1:
                    idx_in_excerpt = int(offset_in_gap)
            else:
                idx_in_excerpt = int(offset_in_gap)
            # Map excerpt-local position back to absolute text position.
            # Walk past any "[...N chars omitted...]" markers preceding.
            abs_pos = _map_excerpt_to_absolute(excerpt, idx_in_excerpt, gap["gap_start"])
        else:
            continue
        # Sanity: must lie within the gap range
        if abs_pos < gap["gap_start"] or abs_pos >= gap["gap_end"]:
            logger.warning(
                "anchor_gap_fill_pos_out_of_range",
                item=item_number,
                abs_pos=abs_pos,
                gap_range=[gap["gap_start"], gap["gap_end"]],
            )
            continue
        confidence = float(entry.get("confidence", 0.7))
        status = str(entry.get("status", "")).strip()
        heading_text = entry.get("heading_text") or ""
        new_boundaries.append(
            ItemBoundary(
                item_number=item_number,
                start_pos=abs_pos,
                heading_text=heading_text,
                confidence=confidence,
                source="llm_anchor_gap_fill",
                status_hint=status if status not in ("", "not_found") else "",
            )
        )
        added += 1

    if added == 0:
        logger.info("anchor_gap_fill_no_additions")
        return parse_result

    new_boundaries.sort(key=lambda b: b.start_pos)
    for i, b in enumerate(new_boundaries):
        if i + 1 < len(new_boundaries):
            b.end_pos = new_boundaries[i + 1].start_pos
        else:
            b.end_pos = len(text)

    avg_conf = sum(b.confidence for b in new_boundaries) / len(new_boundaries) if new_boundaries else 0.0
    logger.info(
        "anchor_gap_fill_complete",
        added=added,
        total_now=len(new_boundaries),
        avg_conf=round(avg_conf, 3),
    )
    return ParseResult(
        boundaries=new_boundaries,
        part_boundaries=parse_result.part_boundaries,
        total_chars=parse_result.total_chars,
        items_found=len(new_boundaries),
        confidence_avg=avg_conf,
    )


async def _full_doc_extract(
    text: str,
    parse_result: ParseResult,
    missing: list[str],
    llm_model: str,
    user_api_key: Optional[str],
    trace_id: str,
) -> ParseResult:
    """Full-document extraction: send the entire normalized text to a
    long-context LLM (Gemini 3.1 Pro preferred) along with anchors and
    missing items. The LLM returns absolute char positions in the full
    document, which we validate by substring search.

    This is the heavy-hammer path used for filings like Citi 2026 where
    the rule parser + per-boundary refine missed >50% of items. Cost is
    ~$0.10 per filing on Gemini, latency ~30-60s — but coverage jumps
    from 30-50% to 90%+ on the challenging cases.
    """
    try:
        llm = get_llm(
            model_name=llm_model,
            user_openrouter_key=user_api_key,
            temperature=0.0,
            json_mode=True,
        )
    except TypeError:
        llm = get_llm(model_name=llm_model, user_openrouter_key=user_api_key, temperature=0.0)
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        raise LLMStageError(
            "SEC full-doc-extract LLM init failed",
            stage="stage2.full_doc_extract",
            model_id=llm_model,
            original=e,
        ) from e

    # Build user message: items + anchors + missing + full doc.
    item_lines = []
    found_items = {b.item_number for b in parse_result.boundaries}
    for it in STANDARD_10K_ITEMS:
        marker = "ANCHOR" if it["item_number"] in found_items else "MISSING"
        item_lines.append(f"  [{marker}] Item {it['item_number']}: {it['item_title']}")

    anchor_lines = []
    for b in sorted(parse_result.boundaries, key=lambda x: x.start_pos):
        anchor_lines.append(
            f"  Item {b.item_number} @ char {b.start_pos} ({b.heading_text!r})"
        )

    user_text = (
        "STANDARD 10-K ITEMS:\n"
        + "\n".join(item_lines)
        + "\n\nKNOWN ANCHORS (rule parser found these — DO NOT re-locate):\n"
        + ("\n".join(anchor_lines) or "  (none)")
        + f"\n\nMISSING ITEMS YOU MUST FIND: {missing}\n\n"
        + f"FULL DOCUMENT TEXT ({len(text)} chars):\n---\n"
        + text
        + "\n---\n\nReturn one JSON ARRAY with one object per MISSING item, using "
        + "absolute start_pos in the FULL DOCUMENT TEXT above."
    )

    logger.info(
        "full_doc_extract_invoking",
        anchors=len(parse_result.boundaries),
        missing=len(missing),
        doc_chars=len(text),
        model=llm_model,
    )

    start_time = time.time()
    messages = [
        SystemMessage(content=FULL_DOC_EXTRACTION_PROMPT),
        HumanMessage(content=user_text),
    ]
    try:
        response = await llm.ainvoke(messages)
    except Exception as e:
        from src.shared.llm_errors import LLMStageError

        if isinstance(e, LLMStageError):
            raise
        logger.warning("full_doc_extract_llm_call_failed", err=str(e)[:200])
        return parse_result

    latency_ms = (time.time() - start_time) * 1000
    response_text = coerce_message_text(getattr(response, "content", response))

    tokens_in = (len(FULL_DOC_EXTRACTION_PROMPT) + len(user_text)) // 4
    tokens_out = len(response_text) // 4
    cost_tracker.record_call(
        model=llm_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        task="task3_sec",
        operation="full_doc_extract",
        trace_id=trace_id,
    )

    results = extract_json_array(response_text)
    if not isinstance(results, list):
        obj = extract_json_object(response_text)
        if isinstance(obj, dict):
            for key in ("items", "results", "missing", "found_items"):
                if isinstance(obj.get(key), list):
                    results = obj[key]
                    break
    if not isinstance(results, list):
        logger.warning("full_doc_extract_parse_failed", raw=response_text[:300])
        return parse_result

    new_boundaries = list(parse_result.boundaries)
    added = 0
    rejected_pos = 0
    for entry in results:
        if not isinstance(entry, dict):
            continue
        item_number = str(entry.get("item_number", "")).upper().strip()
        if not item_number or item_number not in missing:
            continue
        found = bool(entry.get("found", False))
        if not found:
            continue
        # Validate the LLM's start_pos by searching for the heading_text
        # in the document. If the LLM's position is off by a few chars
        # but the heading_text is correct, we self-correct via substring.
        start_pos = entry.get("start_pos")
        heading_text = (entry.get("heading_text") or "").strip()
        # Try heading_text first (more reliable than LLM-supplied pos)
        if heading_text and len(heading_text) >= 4:
            idx = text.find(heading_text)
            if idx != -1:
                start_pos = idx
            else:
                # Try case-insensitive
                idx = text.lower().find(heading_text.lower())
                if idx != -1:
                    start_pos = idx
        if not isinstance(start_pos, (int, float)) or start_pos < 0 or start_pos >= len(text):
            rejected_pos += 1
            continue
        confidence = float(entry.get("confidence", 0.7))
        status = str(entry.get("status", "")).strip()
        new_boundaries.append(
            ItemBoundary(
                item_number=item_number,
                start_pos=int(start_pos),
                heading_text=heading_text or item_number,
                confidence=confidence,
                source="llm_full_doc_extract",
                status_hint=status if status not in ("", "not_found") else "",
            )
        )
        added += 1

    if rejected_pos:
        logger.warning("full_doc_extract_rejected_positions", count=rejected_pos)

    if added == 0:
        logger.info("full_doc_extract_no_additions")
        return parse_result

    new_boundaries.sort(key=lambda b: b.start_pos)
    for i, b in enumerate(new_boundaries):
        if i + 1 < len(new_boundaries):
            b.end_pos = new_boundaries[i + 1].start_pos
        else:
            b.end_pos = len(text)

    avg_conf = sum(b.confidence for b in new_boundaries) / len(new_boundaries) if new_boundaries else 0.0
    logger.info(
        "full_doc_extract_complete",
        added=added,
        total_now=len(new_boundaries),
        avg_conf=round(avg_conf, 3),
    )
    return ParseResult(
        boundaries=new_boundaries,
        part_boundaries=parse_result.part_boundaries,
        total_chars=parse_result.total_chars,
        items_found=len(new_boundaries),
        confidence_avg=avg_conf,
    )


def _map_excerpt_to_absolute(excerpt: str, idx_in_excerpt: int, gap_start: int) -> int:
    """Map a position inside an excerpt (which may contain '[...N chars
    omitted...]' bridges) back to the absolute position in the original
    text. Each omitted-bridge adds back the bridged char count."""
    import re as _re

    bridge_re = _re.compile(r"\[\.\.\.(\d+)\s+chars\s+omitted\.\.\.\]")
    pos = 0
    abs_pos = gap_start
    # Walk through the excerpt looking for bridges before idx_in_excerpt
    while pos < idx_in_excerpt:
        m = bridge_re.search(excerpt, pos)
        if m is None or m.start() >= idx_in_excerpt:
            # No more bridges before our position
            abs_pos += (idx_in_excerpt - pos)
            return abs_pos
        # Add chars before the bridge
        abs_pos += (m.start() - pos)
        # Add the bridge's omitted chars
        try:
            abs_pos += int(m.group(1))
        except (ValueError, TypeError):
            pass
        pos = m.end()
    return abs_pos
