"""
Rule-Based Parser for SEC 10-K Filings (Stage 1).

Zero-cost deterministic parsing that handles ~70% of modern filings.
Uses regex patterns to detect item headings and boundaries.

Strategies:
1. Strong heading detection (bold/caps + standard patterns)
2. Table of Contents cross-reference
3. Part boundary detection
4. Fuzzy title matching for non-standard headings
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.shared.logger import get_logger
from src.task3_sec.schemas import (
    ITEM_TITLE_VARIANTS,
    STANDARD_10K_ITEMS,
    ItemStatus,
)

logger = get_logger("rule_parser")


@dataclass
class ItemBoundary:
    """Detected boundary for an item in the source text."""

    item_number: str
    start_pos: int
    end_pos: int = -1  # -1 means "until next item"
    heading_text: str = ""
    confidence: float = 0.0
    source: str = ""  # "heading_regex", "toc", "part_boundary"
    status_hint: str = ""  # optional LLM-refined status hint


@dataclass
class ParseResult:
    """Result of rule-based parsing."""

    boundaries: list[ItemBoundary] = field(default_factory=list)
    part_boundaries: dict[str, int] = field(default_factory=dict)
    format_type: str = "html"
    total_chars: int = 0
    items_found: int = 0
    confidence_avg: float = 0.0


# Regex patterns for item heading detection (ordered by specificity)
_ITEM_HEADING_PATTERNS = [
    # Pattern 1: "ITEM 1." or "Item 1A." — strongest signal
    re.compile(
        r"(?:^|\n)\s*"
        r"(?:ITEM|Item)\s+"
        r"(\d+[A-Ca-c]?)"
        r"\s*[\.\:\—\-]+\s*"
        r"([A-Z\[\u2018\u2019\u201C\u201D][^\n]{0,160}?)"
        r"\s*$",
        re.MULTILINE,
    ),
    # Pattern 2: "ITEM 1.\nBusiness" — common after HTML span/table normalization
    re.compile(
        r"(?:^|\n)\s*"
        r"(?:ITEM|Item)\s+"
        r"(\d+[A-Ca-c]?)"
        r"\s*[\.\:\—\-]?\s*"
        r"(?:\n\s*){1,2}"
        r"([A-Z\[\u2018\u2019\u201C\u201D][^\n]{3,160}?)"
        r"\s*$",
        re.MULTILINE,
    ),
    # Pattern 3: "ITEM 1" (no period) followed by title on same line
    re.compile(
        r"(?:^|\n)\s*"
        r"(?:ITEM|Item)\s+"
        r"(\d+[A-Ca-c]?)"
        r"\s+"
        r"([A-Z\[\u2018\u2019\u201C\u201D][^\n]{3,160}?)"
        r"\s*$",
        re.MULTILINE,
    ),
    # Pattern 4: ALL CAPS variant — "ITEM 1. BUSINESS"
    re.compile(
        r"(?:^|\n)\s*"
        r"ITEM\s+"
        r"(\d+[A-Ca-c]?)"
        r"\s*[\.\:\—\-]+\s*"
        r"([A-Z\s,\'\"\-\&]{5,120}?)"
        r"\s*$",
        re.MULTILINE,
    ),
]

# Part heading patterns
_PART_HEADING_PATTERNS = [
    re.compile(r"(?:^|\n)\s*PART\s+(I{1,3}V?|IV|[1-4])\s*(?:[\.\:\—\-]|\s*$)", re.MULTILINE | re.IGNORECASE),
]

# Incorporated by reference patterns
_INCORPORATED_PATTERNS = [
    re.compile(r"(?i)incorporat\w*\s+(?:herein\s+)?by\s+reference", re.IGNORECASE),
    re.compile(r"(?i)(?:proxy|definitive proxy)\s+statement", re.IGNORECASE),
    re.compile(r"(?i)DEF\s*14A", re.IGNORECASE),
]

# Not applicable / Reserved patterns
_NOT_APPLICABLE_PATTERNS = [
    re.compile(r"(?i)not\s+applicable", re.IGNORECASE),
    re.compile(r"(?i)none\s*\.", re.IGNORECASE),
]

_STANDARD_ITEM_NUMBERS = {item["item_number"] for item in STANDARD_10K_ITEMS}


def _normalize_part_number(raw: str) -> str:
    """Convert part number to Roman numeral format."""
    mapping = {"1": "I", "2": "II", "3": "III", "4": "IV"}
    return mapping.get(raw.strip(), raw.strip().upper())


def _item_number_to_part(item_number: str) -> str:
    """Map item number to its Part."""
    for item_def in STANDARD_10K_ITEMS:
        if item_def["item_number"] == item_number:
            return item_def["part"]
    # Fallback based on number ranges
    num = re.match(r"(\d+)", item_number)
    if num:
        n = int(num.group(1))
        if n <= 4:
            return "I"
        elif n <= 9:
            return "II"
        elif n <= 14:
            return "III"
        else:
            return "IV"
    return "I"


def _get_standard_title(item_number: str) -> str:
    """Get the standard title for an item number."""
    for item_def in STANDARD_10K_ITEMS:
        if item_def["item_number"] == item_number:
            return item_def["item_title"]
    return f"Item {item_number}"


def _match_item_title(item_number: str, detected_title: str) -> float:
    """
    Score how well a detected title matches the expected title for an item.

    Returns:
        Confidence score 0-1
    """
    detected_lower = detected_title.lower().strip()

    if not detected_lower:
        return 0.55

    # Check against known variants
    variants = ITEM_TITLE_VARIANTS.get(item_number.upper(), [])
    for variant in variants:
        if variant.lower() in detected_lower:
            return 0.95

    # Check against standard title
    standard = _get_standard_title(item_number)
    if standard.lower()[:20] in detected_lower:
        return 0.90

    # Weak match — item number matched but title unclear
    return 0.5


def detect_item_headings(text: str) -> list[ItemBoundary]:
    """
    Detect item heading positions using regex patterns.

    Scans the full text for heading patterns, skipping the ToC region
    (headings in ToC should not be confused with actual content headings).

    Returns:
        List of ItemBoundary with positions and confidence scores
    """
    boundaries: list[ItemBoundary] = []
    seen_items: dict[str, list[ItemBoundary]] = {}  # Track duplicates (ToC vs content)

    for pattern in _ITEM_HEADING_PATTERNS:
        for match in pattern.finditer(text):
            item_number = match.group(1).upper()
            heading_text = match.group(2).strip() if match.lastindex >= 2 else ""
            start_pos = match.start()

            if item_number not in _STANDARD_ITEM_NUMBERS:
                continue

            # Score the match
            confidence = _match_item_title(item_number, heading_text)
            if _looks_like_toc_entry(match.group(0), start_pos, len(text)):
                confidence = min(confidence, 0.45)

            boundary = ItemBoundary(
                item_number=item_number,
                start_pos=start_pos,
                heading_text=heading_text,
                confidence=confidence,
                source="heading_regex",
            )

            if item_number not in seen_items:
                seen_items[item_number] = []
            seen_items[item_number].append(boundary)

    # For items that appear multiple times (ToC + content), prefer the LATER one
    # because the first occurrence is usually in the Table of Contents
    for item_number, matches in seen_items.items():
        if len(matches) == 1:
            boundaries.append(matches[0])
        else:
            # Sort by position, take the last occurrence (content, not ToC)
            matches.sort(key=lambda b: b.start_pos)

            # Heuristic: if first match is in the first 15% of doc, it's likely ToC
            doc_length = len(text)
            content_matches = [
                m for m in matches
                if m.start_pos > doc_length * 0.10
            ]

            if content_matches:
                # Take the first content match (after ToC region)
                best = content_matches[0]
                best.confidence = min(best.confidence + 0.05, 1.0)  # Bonus for having ToC confirmation
                boundaries.append(best)
            else:
                boundaries.append(matches[-1])

    # Sort by position
    boundaries.sort(key=lambda b: b.start_pos)

    logger.info("headings_detected", count=len(boundaries),
                items=[b.item_number for b in boundaries])

    return boundaries


def _looks_like_toc_entry(match_text: str, start_pos: int, doc_length: int) -> bool:
    """Return True when a heading match likely came from a table of contents."""
    if start_pos > doc_length * 0.20:
        return False

    compact = " ".join(match_text.split())
    if re.search(r"\.{2,}\s*\d{1,4}\s*$", compact):
        return True
    if re.search(r"\s\d{1,4}\s*$", compact) and len(compact) < 140:
        return True
    return "table of contents" in text_window_prefix(match_text).lower()


def text_window_prefix(value: str) -> str:
    """Normalize a small text window for lightweight pattern checks."""
    return value[:200]


def detect_part_boundaries(text: str) -> dict[str, int]:
    """Detect Part I, II, III, IV boundary positions."""
    parts: dict[str, int] = {}

    for pattern in _PART_HEADING_PATTERNS:
        for match in pattern.finditer(text):
            part = _normalize_part_number(match.group(1))
            pos = match.start()
            # Keep the last occurrence (skip ToC)
            if part not in parts or pos > parts[part]:
                parts[part] = pos

    logger.info("parts_detected", parts=list(parts.keys()))
    return parts


def detect_item_status(content: str) -> ItemStatus:
    """
    Detect the status of an item based on its content.

    Check order matters:
    1. Reserved (most specific — "[Reserved]")
    2. Incorporated by reference
    3. Not applicable / None
    4. Default: extracted
    """
    content_stripped = content.strip()

    # Check for reserved FIRST (before not_applicable, since [Reserved] is short)
    if re.match(r"(?i)^\s*\[?\s*reserved\s*\]?\s*\.?\s*$", content_stripped):
        return ItemStatus.RESERVED

    # Check for incorporated by reference.
    #
    # 1) A "Refer to ... in ... Proxy Statement" pattern in the first 3000 chars
    #    is a stronger signal than the loose proxy-anywhere check — IBM-style
    #    filings list 10+ caption titles between "Refer to" and "Proxy
    #    Statement", pushing the trigger past the original 500-char window.
    head = content_stripped[:3000]
    if re.search(
        r"(?is)\brefer(?:red)?\s+to\b[\s\S]{0,2500}\b(?:proxy|definitive\s+proxy|DEF\s*14A)\b",
        head,
    ):
        return ItemStatus.INCORPORATED_BY_REFERENCE
    # 2) "incorporated by reference" near the start (highly specific)
    if re.search(r"(?i)incorporat\w*\s+(?:herein\s+)?by\s+reference", head):
        return ItemStatus.INCORPORATED_BY_REFERENCE
    # 3) Original loose check (proxy-statement mention) — keep tight at 500
    #    chars so we don't false-fire on long Item 1 sections that mention
    #    a proxy in passing.
    for pattern in _INCORPORATED_PATTERNS:
        if pattern.search(content_stripped[:500]):
            return ItemStatus.INCORPORATED_BY_REFERENCE

    # Check not applicable (short content only)
    if len(content_stripped) < 200:
        if re.search(r"(?i)not\s+applicable", content_stripped):
            return ItemStatus.NOT_APPLICABLE
        if re.match(r"(?i)^\s*none\s*\.?\s*$", content_stripped):
            return ItemStatus.NOT_APPLICABLE

    return ItemStatus.EXTRACTED


def rule_based_parse(text: str) -> ParseResult:
    """
    Stage 1: Rule-based parsing of 10-K text.

    Zero LLM cost. Detects item boundaries using regex patterns.

    Args:
        text: Normalized filing text

    Returns:
        ParseResult with detected boundaries and confidence scores
    """
    total_chars = len(text)

    # Step 1: Detect part boundaries
    part_boundaries = detect_part_boundaries(text)

    # Step 2: Detect item headings
    boundaries = detect_item_headings(text)

    # Step 3: Set end positions (each item ends where the next begins)
    for i, boundary in enumerate(boundaries):
        if i + 1 < len(boundaries):
            boundary.end_pos = boundaries[i + 1].start_pos
        else:
            boundary.end_pos = total_chars

    # Calculate average confidence
    avg_conf = (
        sum(b.confidence for b in boundaries) / len(boundaries)
        if boundaries else 0.0
    )

    result = ParseResult(
        boundaries=boundaries,
        part_boundaries=part_boundaries,
        total_chars=total_chars,
        items_found=len(boundaries),
        confidence_avg=avg_conf,
    )

    logger.info(
        "rule_parse_complete",
        items_found=result.items_found,
        avg_confidence=round(avg_conf, 3),
        total_chars=total_chars,
    )

    return result
