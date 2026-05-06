"""
Validator for SEC 10-K Extraction (Stage 3).

Post-extraction validation:
1. char_range verification (content matches source text at specified positions)
2. Completeness check (all 16+ items accounted for)
3. Status correctness (incorporated/NA/reserved patterns)
4. Content quality (no HTML artifacts, reasonable length)
5. Selective LLM-as-judge for uncertain items
"""

from __future__ import annotations

import re

from src.shared.logger import get_logger
from src.task3_sec.rule_parser import detect_item_status
from src.task3_sec.schemas import (
    STANDARD_10K_ITEMS,
    ExtractedItem,
    ExtractionResult,
    ItemStatus,
)

logger = get_logger("validator")

# Items that were removed or never existed in older filings — never flag as missing.
# Item 6 ("Selected Financial Data") was eliminated by SEC rule release 33-10890 (2021).
# Items 1C ("Cybersecurity") and 9C were added in 2023.
# Item 16 ("Form 10-K Summary") is and always was optional.
_OPTIONAL_ITEMS = {"1C", "9C", "16", "6"}


def validate_extraction(result: ExtractionResult, source_text: str) -> dict:
    """
    Run all validation checks on an extraction result.

    Returns:
        Validation report with per-item and overall scores
    """
    report = {
        "overall_valid": True,
        "checks": [],
        "item_issues": {},
        "coverage": {},
    }

    # Check 1: Coverage — are all expected items present?
    coverage = _check_coverage(result)
    report["coverage"] = coverage
    report["checks"].append(coverage)
    if not coverage["passed"]:
        report["overall_valid"] = False

    # Check 2: Per-item validation
    for item in result.items:
        issues = _validate_item(item, source_text)
        if issues:
            report["item_issues"][item.item_number] = issues
            if any(i["severity"] == "error" for i in issues):
                report["overall_valid"] = False

    # Check 3: Ordering — items should be in standard order
    order_check = _check_item_ordering(result)
    report["checks"].append(order_check)

    # Check 4: No duplicate items
    dupe_check = _check_duplicates(result)
    report["checks"].append(dupe_check)

    logger.info(
        "validation_complete",
        overall_valid=report["overall_valid"],
        total_issues=sum(len(v) for v in report["item_issues"].values()),
    )

    return report


def _check_coverage(result: ExtractionResult) -> dict:
    """Check if all standard items are accounted for."""
    found = {item.item_number for item in result.items}
    expected = {item["item_number"] for item in STANDARD_10K_ITEMS}
    missing = expected - found
    extra = found - expected
    missing_required = missing - _OPTIONAL_ITEMS

    return {
        "check": "coverage",
        # Pass if every *required* item is present. Optional items (1C/9C/16/6)
        # may legitimately be absent depending on filing year/regime.
        "passed": len(missing_required) == 0,
        "found": len(found),
        "expected": len(expected),
        "missing": sorted(missing),
        "missing_required": sorted(missing_required),
        "extra": sorted(extra),
    }


def _validate_item(item: ExtractedItem, source_text: str) -> list[dict]:
    """Validate a single extracted item."""
    issues: list[dict] = []

    # NOT_FOUND items use [0, 0] as a placeholder — that's not a real range and
    # carries no content claim, so don't run range checks against them.
    if item.status == ItemStatus.NOT_FOUND:
        return issues

    # Check char_range validity
    if item.char_range and len(item.char_range) == 2:
        start, end = item.char_range
        if start < 0 or end > len(source_text) or start >= end:
            issues.append({
                "check": "char_range_bounds",
                "severity": "error",
                "message": f"Invalid char_range [{start}, {end}] for source of length {len(source_text)}",
            })
        elif item.status == ItemStatus.EXTRACTED and item.content_text:
            # Verify content matches source at char_range
            source_slice = source_text[start:end]
            content_prefix = item.content_text[:100].strip()
            source_prefix = source_slice[:150].strip()

            if content_prefix and content_prefix[:50] not in source_prefix:
                issues.append({
                    "check": "char_range_content_mismatch",
                    "severity": "warning",
                    "message": "Content start doesn't match source at char_range",
                })

    # Check content quality
    if item.status == ItemStatus.EXTRACTED:
        if not item.content_text or len(item.content_text.strip()) < 10:
            # Item 6 was eliminated in 2021 and Item 1B is often "None" — those
            # are not extraction failures. Only flag if the rule parser actually
            # claimed extracted content but produced nothing.
            if item.item_number not in _OPTIONAL_ITEMS and item.item_number != "1B":
                issues.append({
                    "check": "empty_content",
                    "severity": "error",
                    "message": "Extracted item has no content",
                })
        elif len(item.content_text.strip()) < 50:
            issues.append({
                "check": "very_short_content",
                "severity": "warning",
                "message": f"Content is very short ({len(item.content_text)} chars) — may be incomplete",
            })

        # Check for HTML artifacts
        if re.search(r"<(?:div|span|table|tr|td|ix:)", item.content_text[:500]):
            issues.append({
                "check": "html_artifacts",
                "severity": "warning",
                "message": "Content contains HTML tags — normalization may be incomplete",
            })

    # Check status consistency
    if item.status == ItemStatus.INCORPORATED_BY_REFERENCE:
        if not any(
            kw in item.content_text.lower()
            for kw in ["incorporat", "proxy", "def 14a", "reference"]
        ):
            issues.append({
                "check": "status_consistency",
                "severity": "warning",
                "message": "Status is incorporated_by_reference but content doesn't mention it",
            })

    return issues


def _check_item_ordering(result: ExtractionResult) -> dict:
    """Check that items are in the expected order."""
    item_numbers = [item.item_number for item in result.items]

    # Define expected ordering
    expected_order = [item["item_number"] for item in STANDARD_10K_ITEMS]
    expected_map = {num: i for i, num in enumerate(expected_order)}

    out_of_order = []
    for i in range(len(item_numbers) - 1):
        curr_idx = expected_map.get(item_numbers[i], -1)
        next_idx = expected_map.get(item_numbers[i + 1], -1)
        if curr_idx >= 0 and next_idx >= 0 and curr_idx >= next_idx:
            out_of_order.append((item_numbers[i], item_numbers[i + 1]))

    return {
        "check": "ordering",
        "passed": len(out_of_order) == 0,
        "out_of_order_pairs": out_of_order,
    }


def _check_duplicates(result: ExtractionResult) -> dict:
    """Check for duplicate item numbers."""
    seen = {}
    duplicates = []
    for item in result.items:
        if item.item_number in seen:
            duplicates.append(item.item_number)
        seen[item.item_number] = True

    return {
        "check": "no_duplicates",
        "passed": len(duplicates) == 0,
        "duplicates": duplicates,
    }


def fix_common_issues(result: ExtractionResult, source_text: str) -> ExtractionResult:
    """
    Auto-fix common validation issues.

    Fixes:
    - Recalculate char_ranges from content matching
    - Clean HTML artifacts from content
    - Fix status using the same strict heuristic as the rule parser
      (the previous loose 'incorporated' + 'reference' substring check
      misclassified long Item 1 sections that mention both words in
      unrelated contexts, e.g. 'Tesla was incorporated in 2003').
    """
    for item in result.items:
        # Re-detect status using the strict header-zone heuristic.
        # Only override EXTRACTED → other; never demote an explicit non-EXTRACTED
        # status that the parser already locked in based on the heading region.
        if item.status == ItemStatus.EXTRACTED and item.content_text:
            detected_status = detect_item_status(item.content_text)
            if detected_status != ItemStatus.EXTRACTED:
                item.status = detected_status

        # Verify and fix char_range by searching source text
        if item.content_text and item.status == ItemStatus.EXTRACTED:
            content_start = item.content_text[:100].strip()
            if content_start:
                idx = source_text.find(content_start[:50])
                if idx >= 0:
                    item.char_range = [idx, idx + len(item.content_text)]

    return result
