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
from src.task3_sec.fetcher import (
    fetch_filing_content,
    find_10k_filing,
    find_proxy_statement,
    parse_filing_url_metadata,
)
from src.task3_sec.llm_refiner import refine_boundaries
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


async def extract_10k(
    cik: Optional[str] = None,
    accession_number: Optional[str] = None,
    filing_url: Optional[str] = None,
    model_name: Optional[str] = None,
    user_api_key: Optional[str] = None,
    skip_llm: bool = False,
    skip_xbrl: bool = False,
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

    # ========== FETCH FILING ==========
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

    filing_metadata = FilingMetadata(
        cik=filing_info.get("cik", cik or ""),
        company_name=filing_info.get("company_name", ""),
        accession_number=filing_info.get("accession_number", accession_number or ""),
        filing_date=filing_info.get("filing_date", ""),
        filing_url=filing_info.get("filing_url", filing_url or ""),
        form_type=filing_info.get("form_type", "10-K"),
    )

    # ========== STAGE 1: NORMALIZE + RULE-BASED PARSE ==========
    stage1_start = time.time()
    normalized_text, format_type = normalize_filing(raw_content)
    parse_result = rule_based_parse(normalized_text)
    stages_used.append("rule_based")

    logger.info(
        "stage1_complete",
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
    needs_llm = not skip_llm and (
        parse_result.items_found < 10
        or parse_result.confidence_avg < 0.55
        or (parse_result.confidence_avg < 0.75 and not has_all_required)
    )
    if needs_llm:
        stage2_start = time.time()
        try:
            cost_before = cost_tracker.get_session_summary()
            parse_result = await refine_boundaries(
                text=normalized_text,
                parse_result=parse_result,
                model_name=model_name,
                user_api_key=user_api_key,
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
        except Exception as e:
            logger.warning("stage2_failed", error=str(e))
            stages_used.append("llm_refine_failed")

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

    result = fix_common_issues(result, normalized_text)
    validation_report = validate_extraction(result, normalized_text)
    stages_used.append("validation")

    # ========== STAGE 4: XBRL CROSS-VALIDATION ==========
    xbrl_report = {}
    if not skip_xbrl and cik:
        try:
            fiscal_year = _extract_fiscal_year(filing_metadata.filing_date)
            xbrl_report = await cross_validate_financials(
                cik=cik,
                extracted_items=items,
                fiscal_year=fiscal_year,
            )
            stages_used.append("xbrl_cross_check")
        except Exception as e:
            logger.warning("stage4_failed", error=str(e))

    # ========== FINALIZE PROCESSING METADATA ==========
    total_duration = (time.time() - pipeline_start) * 1000

    # Get cost info from tracker
    request_cost = cost_tracker.get_request_cost(trace_id)

    rule_only = sum(
        1 for item in items
        if item.extraction_method == ExtractionMethod.RULE_BASED
    )
    llm_refined = sum(
        1 for item in items
        if item.extraction_method in (ExtractionMethod.LLM_REFINED, ExtractionMethod.HYBRID)
    )

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

    return result


def _build_items(text: str, parse_result: ParseResult) -> list[ExtractedItem]:
    """Build ExtractedItem list from parse result boundaries."""
    items: list[ExtractedItem] = []

    for boundary in parse_result.boundaries:
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

        # Determine extraction method
        method = ExtractionMethod.RULE_BASED
        if boundary.source in ("llm_refined", "llm_missing_detect"):
            method = ExtractionMethod.LLM_REFINED

        # Get standard item info
        item_info = _get_item_info(boundary.item_number)

        items.append(ExtractedItem(
            part=item_info["part"],
            item_number=boundary.item_number,
            item_title=boundary.heading_text or item_info["item_title"],
            content_text=content_body,
            char_range=[start, end],
            status=status,
            confidence=boundary.confidence,
            extraction_method=method,
        ))

    return items


def _fill_missing_items(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Add NOT_FOUND entries for any standard items not detected."""
    found = {item.item_number for item in items}

    for std_item in STANDARD_10K_ITEMS:
        if std_item["item_number"] not in found:
            items.append(ExtractedItem(
                part=std_item["part"],
                item_number=std_item["item_number"],
                item_title=std_item["item_title"],
                content_text="",
                char_range=[0, 0],
                status=ItemStatus.NOT_FOUND,
                confidence=0.0,
                extraction_method=ExtractionMethod.RULE_BASED,
            ))

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
    incorporated = [
        item for item in items
        if item.status == ItemStatus.INCORPORATED_BY_REFERENCE
    ]

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
