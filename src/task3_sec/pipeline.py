"""
SEC 10-K Extraction Pipeline.

4-stage hybrid pipeline:
  Stage 1: Rule-based pre-segmentation ($0 cost, ~70% coverage)
  Stage 2: LLM boundary refinement (only for low-confidence boundaries)
  Stage 3: Validation + auto-fix (char_range, status, content quality)
  Stage 4: XBRL cross-validation (financial number spot-checks)

Orchestrates all modules: fetcher → normalizer → rule_parser → llm_refiner → validator → xbrl_client
"""

from __future__ import annotations

import time
from typing import Optional

from src.shared.cost_tracker import get_cost_tracker
from src.shared.logger import generate_trace_id, get_logger
from src.shared.tracing import attach_metadata, traced
from src.task3_sec.fetcher import (
    fetch_filing_content,
    find_10k_filing,
    find_proxy_statement,
    parse_filing_url_metadata,
)
from src.task3_sec.llm_refiner import anchor_aware_gap_fill, refine_boundaries
from src.task3_sec.normalizer import normalize_filing
from src.task3_sec.rule_parser import (
    ParseResult,
    detect_item_status,
    rule_based_parse,
)
from src.task3_sec.schemas import (
    STANDARD_10K_ITEMS,
    ExtractedItem,
    ExtractionMethod,
    ExtractionResult,
    FilingMetadata,
    ItemStatus,
    ProcessingMetadata,
)
from src.task3_sec.validator import fix_common_issues, validate_extraction
from src.task3_sec.xbrl_client import cross_validate_financials

logger = get_logger("pipeline")
cost_tracker = get_cost_tracker()


@traced(name="task3_extract_10k", tags=["task3", "sec_extraction"])
async def extract_10k(
    cik: Optional[str] = None,
    accession_number: Optional[str] = None,
    filing_url: Optional[str] = None,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    skip_llm: bool = False,
    skip_xbrl: bool = False,
    use_vision: bool = False,
    force_llm: bool = False,
    max_cost_usd: Optional[float] = None,
    progress_callback: Optional[callable] = None,
    trace_id: Optional[str] = None,
) -> ExtractionResult:
    """
    Main extraction pipeline.

    Accepts either (cik + accession_number) or filing_url as input.

    Args:
        cik: Company CIK number
        accession_number: Filing accession number
        filing_url: Direct URL to 10-K filing document
        model_name: LLM model for refinement
        user_api_key: User's API key for LLM calls
        skip_llm: If True, skip Stage 2 (LLM refinement)
        skip_xbrl: If True, skip Stage 4 (XBRL cross-validation)
        use_vision: If True, attach rendered filing snapshots to Stage 2 for
            vision-capable models.
        force_llm: If True, run Stage 2 on the lowest-confidence boundaries
            even when the rule parser is otherwise confident. Used for live
            differential benchmarks.
        trace_id: Request trace ID

    Returns:
        ExtractionResult with structured items and metadata
    """
    if trace_id is None:
        trace_id = generate_trace_id()

    pipeline_start = time.time()
    stages_used: list[str] = []
    logger.info(
        "pipeline_start",
        cik=cik,
        accession=accession_number,
        url=filing_url,
        trace_id=trace_id,
    )

    async def _emit(event: str, **payload) -> None:
        """Best-effort progress emit; never break the pipeline if callback fails."""
        if not progress_callback:
            return
        try:
            await progress_callback({"event": event, **payload})
        except Exception as e:
            logger.warning("t3_progress_callback_failed", error=str(e)[:120])

    await _emit(
        "pipeline_start",
        cik=cik or "",
        accession=accession_number or "",
        url=filing_url or "",
        model=model_name or "default",
        use_vision=use_vision,
        skip_llm=skip_llm,
    )

    # Attach metadata to LangSmith span (no-op if not enabled)
    attach_metadata(
        {
            "trace_id": trace_id or "",
            "cik": cik or "",
            "accession_number": accession_number or "",
            "model_name": model_name or "default",
            "skip_llm": skip_llm,
            "use_vision": use_vision,
            "force_llm": force_llm,
        }
    )

    # ========== FETCH FILING ==========
    await _emit("fetch_start", url=filing_url or "(via SEC API)")
    if filing_url:
        # Direct URL provided
        parsed_url_metadata = parse_filing_url_metadata(filing_url)
        filing_info = {
            "cik": cik or parsed_url_metadata.get("cik", ""),
            "company_name": "",
            "accession_number": accession_number or parsed_url_metadata.get("accession_number", ""),
            "filing_date": "",
            "filing_url": filing_url,
            "primary_document": parsed_url_metadata.get("primary_document", ""),
            "form_type": "10-K",
        }
        raw_content = await fetch_filing_content(filing_url)
    elif cik:
        # Look up via submissions API
        filing_info = await find_10k_filing(cik, accession_number)
        raw_content = await fetch_filing_content(filing_info["filing_url"])
    else:
        raise ValueError("Must provide either (cik + accession_number) or filing_url")
    await _emit(
        "fetch_done",
        bytes=len(raw_content),
        company=filing_info.get("company_name", ""),
        form_type=filing_info.get("form_type", "10-K"),
        filing_date=filing_info.get("filing_date", ""),
    )

    filing_metadata = FilingMetadata(
        cik=filing_info.get("cik", cik or ""),
        company_name=filing_info.get("company_name", ""),
        accession_number=filing_info.get("accession_number", accession_number or ""),
        filing_date=filing_info.get("filing_date", ""),
        filing_url=filing_info.get("filing_url", filing_url or ""),
        form_type=filing_info.get("form_type", "10-K"),
    )

    # ========== STAGE 1: NORMALIZE + RULE-BASED PARSE ==========
    await _emit("stage1_start", stage="normalize_and_rule_parse")
    stage1_start = time.time()
    normalized_text, format_type = normalize_filing(raw_content)
    # Pass raw_content to rule_based_parse so HTML-tag-aware anchor
    # extraction (`html_heading_extractor`) can run alongside text-only
    # detectors. Without this, filings like Citi 2026 lose half their
    # heading anchors.
    parse_result = rule_based_parse(normalized_text, raw_html=raw_content)
    stages_used.append("rule_based")

    logger.info(
        "stage1_complete",
        items_found=parse_result.items_found,
        avg_confidence=round(parse_result.confidence_avg, 3),
        format=format_type,
        duration_ms=round((time.time() - stage1_start) * 1000, 1),
    )
    await _emit(
        "stage1_done",
        items_found=parse_result.items_found,
        avg_confidence=round(parse_result.confidence_avg, 3),
        format=format_type,
        duration_ms=round((time.time() - stage1_start) * 1000, 1),
    )

    # ========== STAGE 2: LLM BOUNDARY REFINEMENT (if needed) ==========
    # Only fire LLM when the rule-based pass is genuinely uncertain. Modern
    # 10-Ks with all standard items present and decent average confidence do
    # NOT need LLM refinement — the rule-based segmentation is already
    # authoritative, and burning 15+ LLM calls per filing risks rate-limit
    # cascades on the free tier.
    required_for_modern = {"1", "1A", "7", "7A", "8", "15"}
    found_items = {b.item_number for b in parse_result.boundaries}
    has_all_required = required_for_modern.issubset(found_items)
    needs_llm = force_llm or (
        not skip_llm
        and (
            parse_result.items_found < 10
            or parse_result.confidence_avg < 0.55
            or (parse_result.confidence_avg < 0.75 and not has_all_required)
        )
    )
    if needs_llm:
        await _emit(
            "stage2_start",
            stage="llm_refine",
            model=model_name or "default",
            use_vision=use_vision,
            current_confidence=round(parse_result.confidence_avg, 3),
            items_below_threshold=sum(1 for b in parse_result.boundaries if b.confidence < 0.55),
        )
        stage2_start = time.time()
        try:
            cost_before = cost_tracker.get_session_summary()
            parse_result = await refine_boundaries(
                text=normalized_text,
                parse_result=parse_result,
                model_name=model_name,
                user_api_key=user_api_key,
                use_vision=use_vision,
                force_refine=force_llm,
                trace_id=trace_id,
            )
            stages_used.append("llm_refine")

            cost_after = cost_tracker.get_session_summary()
            calls_added = cost_after["total_calls"] - cost_before["total_calls"]

            logger.info(
                "stage2_complete",
                items_found=parse_result.items_found,
                avg_confidence=round(parse_result.confidence_avg, 3),
                llm_calls_added=calls_added,
                duration_ms=round((time.time() - stage2_start) * 1000, 1),
            )
            await _emit(
                "stage2_done",
                items_found=parse_result.items_found,
                avg_confidence=round(parse_result.confidence_avg, 3),
                llm_calls=calls_added,
                duration_ms=round((time.time() - stage2_start) * 1000, 1),
            )

            # Cost-discipline guard — the spec calls for "Max $0.50 per
            # filing". After Stage 2 (the only paid LLM stage in T3) we
            # check whether we're already over budget. If so, skip Stage 3
            # validation re-runs and stop accumulating spend; the items we
            # have are still returned with a failure_modes flag.
            from src.shared.cost_tracker import BudgetExceededError

            try:
                cost_tracker.check_request_budget(trace_id, cap_usd=max_cost_usd, task="task3_sec")
            except BudgetExceededError as be:
                logger.warning(
                    "budget_cap_hit_after_stage2",
                    trace_id=trace_id,
                    cost=round(be.cost_so_far, 6),
                    cap=be.cap_usd,
                )
                await _emit(
                    "budget_cap_hit",
                    cost_usd=round(be.cost_so_far, 6),
                    cap_usd=be.cap_usd,
                )
                stages_used.append("budget_cap_hit")
                # Skip remaining LLM-driven stages
                skip_llm = True
        except Exception as e:
            from src.shared.llm_errors import LLMStageError

            # Soft-fail: Stage 2 boundary-refine is supplementary —
            # rule-based + TOC + HTML anchors already get us to 90%+
            # coverage. If the LLM rate-limits or 503s, log and
            # continue to Stage 2b (anchor_gap_fill) which is also
            # LLM-driven but uses a single-call full-doc approach.
            if isinstance(e, LLMStageError):
                logger.warning("stage2_soft_fail_llm_error", err=str(e)[:200])
                await _emit("stage2_failed", error=e.to_envelope())
            else:
                logger.warning("stage2_failed", error=str(e))
                await _emit("stage2_failed", error=str(e)[:120])
            stages_used.append("llm_refine_failed")
    else:
        await _emit(
            "stage2_skipped",
            reason="rule_parser_confident",
            avg_confidence=round(parse_result.confidence_avg, 3),
            items_found=parse_result.items_found,
        )

    # ========== STAGE 2B: ANCHOR-AWARE GAP-FILL ==========
    # When rule + per-boundary refine still leaves us with critical
    # coverage gaps (e.g. Citi 2026 even with HTML anchors gets only
    # ~12 items vs 22 expected), run the single-call anchor-aware
    # gap-fill. ONE LLM call with all anchors + all missing items +
    # gap excerpts — vastly more effective than per-boundary loop
    # when most items have no boundary at all.
    #
    # Trigger: force_llm OR (not skip_llm AND items_found < 18).
    # 18 is the lower bound for "complete modern filing" (22 items
    # minus ~4 optional like 1B/1C/6/16 that may legitimately be N/A).
    needs_gap_fill = force_llm or (not skip_llm and parse_result.items_found < 18)
    if needs_gap_fill:
        gap_fill_before = parse_result.items_found
        await _emit(
            "stage2b_start",
            stage="anchor_gap_fill",
            anchors=gap_fill_before,
            missing_count=max(0, 22 - gap_fill_before),
        )
        try:
            stage2b_start = time.time()
            parse_result = await anchor_aware_gap_fill(
                text=normalized_text,
                parse_result=parse_result,
                model_name=model_name,
                user_api_key=user_api_key,
                trace_id=trace_id,
            )
            stages_used.append("anchor_gap_fill")
            await _emit(
                "stage2b_done",
                items_found=parse_result.items_found,
                added=parse_result.items_found - gap_fill_before,
                duration_ms=round((time.time() - stage2b_start) * 1000, 1),
            )
            logger.info(
                "stage2b_complete",
                items_found=parse_result.items_found,
                added=parse_result.items_found - gap_fill_before,
            )
        except Exception as e:
            from src.shared.llm_errors import LLMStageError

            if isinstance(e, LLMStageError):
                # Soft-fail — gap-fill is supplementary; the main refine
                # path already succeeded (or was skipped). Don't crash the
                # whole pipeline because of it.
                logger.warning("stage2b_soft_fail", err=str(e)[:200])
                stages_used.append("anchor_gap_fill_failed")
                await _emit("stage2b_failed", error=str(e)[:160])
            else:
                logger.warning("stage2b_failed", error=str(e))
                stages_used.append("anchor_gap_fill_failed")
                await _emit("stage2b_failed", error=str(e)[:160])

    # ========== BUILD EXTRACTED ITEMS ==========
    items = _build_items(normalized_text, parse_result)

    # ========== HANDLE INCORPORATED BY REFERENCE ==========
    if cik:
        await _resolve_incorporations(items, cik, filing_metadata.filing_date)

    # ========== FILL MISSING ITEMS ==========
    items = _fill_missing_items(items)

    # ========== STAGE 3: VALIDATION + AUTO-FIX ==========
    result = ExtractionResult(
        filing_metadata=filing_metadata,
        items=items,
        processing_metadata=ProcessingMetadata(
            format_detected=format_type,
            filing_char_count=len(normalized_text),
        ),
    )

    await _emit("stage3_start", stage="validation")
    result = fix_common_issues(result, normalized_text)
    validation_report = validate_extraction(result, normalized_text)
    stages_used.append("validation")
    await _emit(
        "stage3_done",
        overall_valid=validation_report.get("overall_valid", True),
        issue_count=len(validation_report.get("issues", [])),
    )

    # ========== STAGE 4: XBRL CROSS-VALIDATION ==========
    xbrl_report = {}
    if not skip_xbrl and cik:
        await _emit("stage4_start", stage="xbrl_cross_check")
        try:
            fiscal_year = _extract_fiscal_year(filing_metadata.filing_date)
            xbrl_report = await cross_validate_financials(
                cik=cik,
                extracted_items=items,
                fiscal_year=fiscal_year,
            )
            stages_used.append("xbrl_cross_check")
            await _emit(
                "stage4_done",
                xbrl_status=xbrl_report.get("status", ""),
                checks=len(xbrl_report.get("checks", [])),
            )
        except Exception as e:
            logger.warning("stage4_failed", error=str(e))
            await _emit("stage4_failed", error=str(e)[:120])

    # ========== FINALIZE PROCESSING METADATA ==========
    total_duration = (time.time() - pipeline_start) * 1000

    # Get cost info from tracker
    request_cost = cost_tracker.get_request_cost(trace_id)

    rule_only = sum(1 for item in items if item.extraction_method == ExtractionMethod.RULE_BASED)
    llm_refined = sum(
        1 for item in items if item.extraction_method in (ExtractionMethod.LLM_REFINED, ExtractionMethod.HYBRID)
    )

    # Honesty metrics — see ProcessingMetadata docstring. expected_count is
    # the size of STANDARD_10K_ITEMS; extracted_count is how many of `items`
    # were actually populated (any status other than NOT_FOUND).
    from src.task3_sec.schemas import STANDARD_10K_ITEMS as _STD_ITEMS

    expected_count = len(_STD_ITEMS)
    extracted_count = sum(1 for item in items if item.status != ItemStatus.NOT_FOUND)
    # Clamp to [0, 1]; defensive against dedup edge cases where intermediate
    # boundary lists temporarily exceed expected (Pydantic schema enforces 0-1).
    completeness = round(min(1.0, extracted_count / max(expected_count, 1)), 3)

    result.processing_metadata = ProcessingMetadata(
        total_tokens_in=request_cost.get("tokens_in", 0),
        total_tokens_out=request_cost.get("tokens_out", 0),
        llm_calls=request_cost.get("calls", 0),
        rule_only_items=rule_only,
        llm_refined_items=llm_refined,
        total_cost_usd=request_cost.get("cost_usd", 0.0),
        total_latency_ms=round(total_duration, 1),
        stages_used=stages_used,
        filing_char_count=len(normalized_text),
        format_detected=format_type,
        validation_report=validation_report,
        xbrl_report=xbrl_report,
        extracted_count=extracted_count,
        expected_count=expected_count,
        extraction_completeness=completeness,
    )

    logger.info(
        "pipeline_complete",
        items=len(items),
        rule_only=rule_only,
        llm_refined=llm_refined,
        cost_usd=round(result.processing_metadata.total_cost_usd, 6),
        latency_ms=round(total_duration, 1),
        stages=stages_used,
        trace_id=trace_id,
    )

    # Status counts for the streaming UI summary line
    status_counts: dict[str, int] = {}
    for it in items:
        s = it.status.value if hasattr(it.status, "value") else str(it.status)
        status_counts[s] = status_counts.get(s, 0) + 1
    await _emit(
        "pipeline_complete",
        items=len(items),
        rule_only=rule_only,
        llm_refined=llm_refined,
        cost_usd=round(result.processing_metadata.total_cost_usd, 6),
        latency_ms=round(total_duration, 1),
        stages=stages_used,
        status_counts=status_counts,
    )

    return result


def _build_items(text: str, parse_result: ParseResult) -> list[ExtractedItem]:
    """Build ExtractedItem list from parse result boundaries.

    Dedupes by item_number: when multiple boundaries point to the same
    item (cover_toc_status + llm_refined, or html_anchor + title_fallback),
    keeps the one with the longest content body. LLM-refined boundaries
    win ties because they're verified against actual text rather than
    inferred from a TOC table.
    """
    items: list[ExtractedItem] = []

    # Dedupe boundaries by item_number BEFORE building items.
    #
    # Three-tier scoring (highest first):
    #   1. **Authoritative non-extracted status_hint wins**. TOC / cross-
    #      reference / master-IBR detectors emit hints like "reserved",
    #      "not_applicable", "incorporated_by_reference". When the filing's
    #      own TOC explicitly says Item N is reserved, that trumps any
    #      body anchor (which is often a false positive — e.g. an html
    #      <span> matching "Selected Financial Data" subheading when Item
    #      6 is actually [Reserved]).
    #   2. **Longest content wins among same-status boundaries**. Real
    #      body prose beats short cover-page snippets.
    #   3. **Source priority breaks ties**. llm_refined > html_anchor >
    #      title_only_fallback > regex > TOC/cross-ref/IBR.
    _SOURCE_PRIORITY = {
        "llm_refined": 5,
        "llm_full_doc_extract": 5,
        "llm_anchor_gap_fill": 5,
        "llm_missing_detect": 4,
        "html_anchor": 3,
        "heading_regex": 3,
        "title_only_fallback": 2,
        "heading_regex_toc_suspect": 2,
        "master_ibr_declaration": 1,
        "cover_toc_status": 1,
        "end_cross_reference": 1,
    }
    _AUTHORITATIVE_NON_EXTRACTED = {
        "not_applicable",
        "reserved",
        "incorporated_by_reference",
    }

    def _score(b) -> tuple:
        content_len = max(0, (b.end_pos if b.end_pos > 0 else len(text)) - b.start_pos)
        # Tier 0: authoritative hint? (TOC-declared reserved/N-A/IBR is the truth)
        authoritative = 1 if (b.status_hint in _AUTHORITATIVE_NON_EXTRACTED) else 0
        return (authoritative, content_len, _SOURCE_PRIORITY.get(b.source, 0))

    from src.task3_sec.rule_parser import ItemBoundary as _ItemBoundary

    best_per_item: dict[str, _ItemBoundary] = {}
    for boundary in parse_result.boundaries:
        existing = best_per_item.get(boundary.item_number)
        if existing is None or _score(boundary) > _score(existing):
            best_per_item[boundary.item_number] = boundary

    deduped = sorted(best_per_item.values(), key=lambda b: b.start_pos)

    for boundary in deduped:
        start = boundary.start_pos
        end = boundary.end_pos if boundary.end_pos > 0 else len(text)

        content = text[start:end].strip()

        # Remove the heading from content (content starts after the heading line)
        lines = content.split("\n", 1)
        if len(lines) > 1:
            content_body = lines[1].strip()
        else:
            content_body = content

        # Detect status from content
        status = detect_item_status(content_body)
        if boundary.status_hint:
            try:
                hinted_status = ItemStatus(boundary.status_hint)
                # Deterministic non-extracted statuses are more trustworthy
                # than an LLM "extracted" hint. LLM hints mainly help when
                # visual context catches N/A / Reserved / Proxy-reference
                # language that text heuristics missed.
                if status == ItemStatus.EXTRACTED or hinted_status != ItemStatus.EXTRACTED:
                    status = hinted_status
            except ValueError:
                pass

        # Determine extraction method
        method = ExtractionMethod.RULE_BASED
        if boundary.source in ("llm_refined", "llm_missing_detect"):
            method = ExtractionMethod.LLM_REFINED

        # Get standard item info
        item_info = _get_item_info(boundary.item_number)

        items.append(
            ExtractedItem(
                part=item_info["part"],
                item_number=boundary.item_number,
                item_title=boundary.heading_text or item_info["item_title"],
                content_text=content_body,
                char_range=[start, end],
                status=status,
                confidence=boundary.confidence,
                extraction_method=method,
            )
        )

    return items


def _fill_missing_items(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Add placeholder entries for any standard items not detected.

    Optional items that are missing get a friendlier default status:
      - Item 16 (Form 10-K Summary): always optional per SEC instructions →
        not_applicable (most filers omit it)
      - Item 6 (Selected Financial Data): eliminated by SEC release 33-10890
        in 2021 → reserved
    Other missing items remain NOT_FOUND so the honest reporting layer can
    surface coverage gaps."""
    found = {item.item_number for item in items}

    # Items where "missing" has a natural non-not_found interpretation.
    # See SEC release 33-10890 (2021) for Item 6 elimination, and Reg S-K
    # Item 16 instruction (optional).
    _OPTIONAL_AUTO_STATUS: dict[str, tuple[ItemStatus, str]] = {
        "16": (
            ItemStatus.NOT_APPLICABLE,
            "Form 10-K Summary is optional per SEC instructions; "
            "this filer did not include one.",
        ),
        "6": (
            ItemStatus.RESERVED,
            "Item 6 (Selected Financial Data) was eliminated by SEC release "
            "33-10890 in 2021 and is no longer required.",
        ),
    }

    for std_item in STANDARD_10K_ITEMS:
        if std_item["item_number"] not in found:
            auto = _OPTIONAL_AUTO_STATUS.get(std_item["item_number"])
            if auto is not None:
                status, note = auto
                items.append(
                    ExtractedItem(
                        part=std_item["part"],
                        item_number=std_item["item_number"],
                        item_title=std_item["item_title"],
                        content_text=note,
                        char_range=[0, 0],
                        status=status,
                        confidence=0.70,
                        extraction_method=ExtractionMethod.RULE_BASED,
                    )
                )
            else:
                items.append(
                    ExtractedItem(
                        part=std_item["part"],
                        item_number=std_item["item_number"],
                        item_title=std_item["item_title"],
                        content_text="",
                        char_range=[0, 0],
                        status=ItemStatus.NOT_FOUND,
                        confidence=0.0,
                        extraction_method=ExtractionMethod.RULE_BASED,
                    )
                )

    # Sort by standard order
    order = {item["item_number"]: i for i, item in enumerate(STANDARD_10K_ITEMS)}
    items.sort(key=lambda x: order.get(x.item_number, 99))

    return items


async def _resolve_incorporations(
    items: list[ExtractedItem],
    cik: str,
    filing_date: str,
) -> None:
    """Resolve incorporated-by-reference items by finding proxy statements."""
    incorporated = [item for item in items if item.status == ItemStatus.INCORPORATED_BY_REFERENCE]

    if not incorporated:
        return

    # Extract year from filing date
    year = _extract_fiscal_year(filing_date)
    if not year:
        return

    logger.info(
        "resolving_incorporations",
        count=len(incorporated),
        cik=cik,
        year=year,
    )

    try:
        proxy = await find_proxy_statement(cik, year)
        if proxy:
            for item in incorporated:
                item.reference_document = "DEF 14A"
                item.reference_url = proxy.get("url", "")
    except Exception as e:
        logger.warning("proxy_resolution_failed", error=str(e))


def _get_item_info(item_number: str) -> dict:
    """Get standard item info by number."""
    for item in STANDARD_10K_ITEMS:
        if item["item_number"] == item_number:
            return item
    return {"part": "I", "item_number": item_number, "item_title": f"Item {item_number}"}


def _extract_fiscal_year(filing_date: str) -> Optional[int]:
    """Extract fiscal year from filing date string."""
    if not filing_date:
        return None
    try:
        # Filing date is usually YYYY-MM-DD; fiscal year is typically year - 1
        year = int(filing_date[:4])
        month = int(filing_date[5:7]) if len(filing_date) > 5 else 1
        # If filed in Jan-Mar, it's likely for previous fiscal year
        if month <= 3:
            return year - 1
        return year
    except (ValueError, IndexError):
        return None
