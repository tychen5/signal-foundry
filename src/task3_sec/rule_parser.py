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
            only = matches[0]
            # Single-match TOC suppression: when the rule parser only matched
            # ONE occurrence of an item AND that match sits in the document's
            # first ~10% region (the typical ToC zone), it's almost certainly
            # the TOC entry — the actual body heading was likely wrapped in
            # an HTML pattern that defeated our regex (e.g. <span>-broken,
            # &nbsp;-padded, <a name="...">-anchored). Without this guard,
            # we'd accept the TOC entry as a body boundary and extract
            # cross-reference list content instead of the real prose
            # (the Intel-2026 failure mode surfaced on 2026-05-15).
            #
            # Mitigation: lower confidence to <0.55 so pipeline.py's Stage 2
            # trigger fires and the LLM refiner can re-locate the real body
            # heading using a wider boundary context window.
            #
            # Detection signal: a small window around the match start (we
            # don't preserve the full match string, so we re-scan ±80 chars).
            # Position-only check is intentionally conservative — we only
            # downweight when the match sits in the first 10% of the doc.
            doc_len = max(len(text), 1)
            doc_pct = only.start_pos / doc_len
            window_start = max(0, only.start_pos - 40)
            window_end = min(len(text), only.start_pos + 200)
            local_window = text[window_start:window_end]
            in_toc_region = doc_pct < 0.10
            has_toc_markers = _looks_like_toc_entry(local_window, only.start_pos, doc_len)
            if in_toc_region or has_toc_markers:
                only.confidence = min(only.confidence, 0.40)
                only.source = "heading_regex_toc_suspect"
                logger.info(
                    "single_match_in_toc_region",
                    item=item_number,
                    pos=only.start_pos,
                    doc_pct=round(doc_pct * 100, 1),
                    in_toc_region=in_toc_region,
                    has_toc_markers=has_toc_markers,
                )
            boundaries.append(only)
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


# Item-number -> canonical title slugs used by the title-only fallback
# detector. These are the body-heading anchors used by filers (Citi 2026,
# Intel 2026, several banking-layout XBRL filings) whose HTML strips
# "Item N." from the prose and renders the section title alone.
#
# Each variant list is ORDER-MATTERS — most-specific first. The detector
# stops on first hit per item so a phrase like "Disclosure Controls and
# Procedures" must come before the bare "Controls and Procedures".
_TITLE_ONLY_HEADINGS: list[tuple[str, list[str]]] = [
    ("1", ["our business", "business"]),
    ("1A", ["risk factors"]),
    ("1B", ["unresolved staff comments"]),
    ("1C", ["cybersecurity"]),
    ("2", ["properties"]),
    ("3", ["legal proceedings"]),
    ("4", ["mine safety disclosures", "mine safety"]),
    ("5", [
        "market for registrant's common equity",
        "market for registrant",
        "market for the registrant",
        "market for our common stock",
        "market for our common equity",
    ]),
    ("6", ["selected financial data", "[reserved]"]),
    ("7", [
        "management's discussion and analysis",
        "managements discussion and analysis",
        "management discussion and analysis",
    ]),
    ("7A", [
        "quantitative and qualitative disclosures about market risk",
        "quantitative and qualitative disclosures",
    ]),
    ("8", [
        "financial statements and supplementary data",
        "consolidated financial statements",
        "report of independent registered public accounting firm",
    ]),
    ("9", [
        "changes in and disagreements with accountants on accounting and financial disclosure",
        "changes in and disagreements with accountants",
    ]),
    ("9A", [
        "disclosure controls and procedures",
        "controls and procedures",
    ]),
    ("9B", ["other information"]),
    ("9C", [
        "disclosure regarding foreign jurisdictions that prevent inspections",
        "disclosure regarding foreign jurisdictions",
        "foreign jurisdictions that prevent inspections",
    ]),
    ("10", [
        "directors, executive officers and corporate governance",
        "directors, executive officers, and corporate governance",
        "information about our executive officers",
        "executive officers of the registrant",
    ]),
    ("11", ["executive compensation"]),
    ("12", [
        "security ownership of certain beneficial owners and management",
        "security ownership of certain beneficial owners",
    ]),
    ("13", [
        "certain relationships and related transactions, and director independence",
        "certain relationships and related transactions",
    ]),
    ("14", [
        "principal accountant fees and services",
        "principal accounting fees and services",
    ]),
    ("15", [
        "exhibits and financial statement schedules",
        "exhibits, financial statement schedules",
        "exhibit index",
    ]),
    ("16", ["form 10-k summary"]),
]


def detect_item_headings_by_title(
    text: str,
    body_start_pct: float = 0.10,
    body_end_pct: float = 0.90,
) -> list[ItemBoundary]:
    """Title-only heading fallback for filings that don't emit literal "Item N."
    text in the body.

    Citi 2026 and Intel 2026 (and several other modern filers — banking
    layout, table-heavy XBRL HTML) render section headings as bold spans
    containing ONLY the title (e.g. "Risk Factors" / "RISK FACTORS" /
    "DISCLOSURE CONTROLS AND PROCEDURES"). The "Item N." label is rendered
    in a separate column / via CSS and never appears as adjacent text.
    The default regex-based detector cannot see these headings, so the
    pipeline returned 0 boundaries (Citi) or matched only the end-of-doc
    cover-page index (Intel).

    This fallback scans the body region (``body_start_pct`` < pos <
    ``body_end_pct``) for known canonical titles and picks the FIRST
    occurrence of each that looks like a standalone heading line. Default
    body window 10%–90% excludes:
      - first 10%: the Table of Contents region (matches there are TOC
        entries, not body)
      - last 10%: the cover-page-style index / signatures / exhibits
        appendix many filers put at end (Intel 2026 has 22 "Item N. ..."
        entries packed into the last 0.7% of doc — those are the END
        index, NOT the body content the parser wants)

    Confidence is 0.55–0.70 so Stage 2 LLM refinement can promote /
    correct them — they're a recovery signal, not gospel.

    Heuristics:
      1. ALL-CAPS variants get a +0.10 confidence bonus
      2. Title-case variants get +0.05
      3. The title must be standalone on a "line" after collapsing
         pipe noise from normalized table cells
      4. Sentence-prose hits ("see Risk Factors below ...") are rejected
         when the preceding 80 chars end mid-word
    """
    doc_len = len(text)
    body_floor = int(doc_len * body_start_pct)
    body_ceil = int(doc_len * body_end_pct)
    boundaries: list[ItemBoundary] = []
    seen: set[str] = set()

    for item_number, variants in _TITLE_ONLY_HEADINGS:
        if item_number in seen:
            continue
        best_pos: int | None = None
        best_text: str = ""
        best_caps_bonus = 0.0
        for variant in variants:
            # Three case variants — most specific first (ALL CAPS wins over
            # title-case wins over lower-case).
            for case_pattern, caps_bonus in (
                (re.escape(variant.upper()), 0.10),
                (re.escape(variant.title()), 0.05),
                (re.escape(variant), 0.0),
            ):
                pat = re.compile(
                    r"(?m)(?:^|\n)\s*(?:\|\s*)*"
                    + case_pattern
                    + r"(?:\s*\|\s*)*\s*$",
                )
                for m in pat.finditer(text, pos=body_floor):
                    if m.start() > body_ceil:
                        # Past the body window — likely end-index pollution
                        break
                    # Reject sentence-prose hits: previous 80 chars must
                    # not end with a lowercase word (would mean we're in
                    # mid-prose "...see Risk Factors below").
                    pre = text[max(0, m.start() - 80):m.start()]
                    if re.search(r"[a-z][a-z]{2,}\s*$", pre.strip()):
                        continue
                    if best_pos is None or m.start() < best_pos:
                        best_pos = m.start()
                        best_text = m.group(0).strip().strip("|").strip()
                        best_caps_bonus = caps_bonus
                if best_pos is not None:
                    break
            if best_pos is not None:
                break
        if best_pos is None:
            continue
        seen.add(item_number)
        confidence = min(0.55 + best_caps_bonus, 0.70)
        boundaries.append(
            ItemBoundary(
                item_number=item_number,
                start_pos=best_pos,
                heading_text=best_text or variants[0],
                confidence=confidence,
                source="title_only_fallback",
            )
        )

    boundaries.sort(key=lambda b: b.start_pos)
    logger.info(
        "title_fallback_detected",
        count=len(boundaries),
        body_window=f"{body_start_pct:.0%}-{body_end_pct:.0%}",
        items=[b.item_number for b in boundaries],
    )
    return boundaries


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

    # Check for reserved FIRST (before not_applicable, since [Reserved] is short).
    # Cover three real SEC patterns:
    #   - "[Reserved]" / "Reserved." (the canonical post-2021 form for Item 6)
    #   - "Removed and Reserved." (the SEC's transitional language for items
    #     like Item 9C 2002–2008, Item 6 2021)
    #   - Short blurbs like "This Item has been reserved." used in older
    #     filings as a polite full-sentence form.
    if re.match(r"(?i)^\s*\[?\s*reserved\s*[\]\.]?\s*$", content_stripped):
        return ItemStatus.RESERVED
    if len(content_stripped) < 200 and re.search(
        r"(?i)\b(?:removed\s+and\s+reserved|(?:has\s+been|is)\s+reserved|item\s+is\s+reserved)\b",
        content_stripped,
    ):
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


def parse_cover_toc_table(text: str) -> dict[str, dict]:
    """Parse the cover-page Table of Contents table that lists every Item with
    its page range / status note.

    Many 10-Ks (Citi, IBM, large filers) include a TOC table on the cover page
    where each row looks like:

        Item Number    Title                                   Page(s)
        1.             Business                                4-36
        1B.            Unresolved Staff Comments               Not Applicable
        6.             Reserved
        9.             Changes in...                           Not Applicable
        10.            Directors, Executive Officers...        304-306*

    After HTML normalization the table is rendered as alternating lines:

        1.
        Business
        4-36

        1B.
        Unresolved Staff Comments
        Not Applicable

    This function walks the cover-page region and builds a mapping:

        {item_number: {
            "status": "extracted" | "not_applicable" | "reserved" |
                      "incorporated_by_reference",
            "page_note": "...",
            "title": "...",
            "toc_pos": <char position of the item entry in TOC>,
        }}

    The status comes from the page-note column:
      - Numeric page range → extracted (item has body section)
      - "Not Applicable" / "N/A" → not_applicable
      - "Reserved" / "[Reserved]" → reserved (or title is "Reserved")
      - Footnote marker only ("*", "**", "***") → incorporated_by_reference
        (the footnote text is the master IBR declaration elsewhere)

    Returns empty dict if no recognizable TOC table found.
    """
    # Scan the cover-page region: skip the first 2 KB of legal preamble,
    # bound to 10 KB after that (TOC tables don't exceed this on real
    # filings). Tighter bounding prevents the parser from walking into
    # financial tables later in the doc that contain stray "9." or "13."
    # row labels and producing false-positive items.
    region_start = 2000 if len(text) > 5000 else 0
    region_end = min(region_start + 10_000, int(len(text) * 0.15) if len(text) > 10000 else len(text))
    region = text[region_start:region_end]

    # State machine: walk through non-empty lines looking for "N." patterns
    lines: list[tuple[int, str]] = []
    pos = 0
    for raw_line in region.split("\n"):
        line = raw_line.strip()
        if line:
            lines.append((region_start + pos, line))
        pos += len(raw_line) + 1  # +1 for the newline

    item_num_re = re.compile(r"^(\d{1,2}[A-C]?)\.?$")
    not_applicable_re = re.compile(r"(?i)^\s*(?:not\s+applicable|n\s*/?\s*a|none)\.?\s*$")
    reserved_re = re.compile(r"(?i)^\s*(?:reserved|\[reserved\])\.?\s*$")
    page_range_re = re.compile(r"^\s*\d+(?:\s*[–\-,\s]\s*\d+)*\s*\*{0,3}\s*$")
    footnote_only_re = re.compile(r"^\s*\*{1,3}\s*$")

    toc: dict[str, dict] = {}
    i = 0
    while i < len(lines):
        line_pos, line = lines[i]
        m = item_num_re.match(line)
        if not m:
            i += 1
            continue
        item_number = m.group(1).upper()
        if item_number not in _STANDARD_ITEM_NUMBERS:
            i += 1
            continue
        # FIRST-occurrence-wins per item: TOC parses the cover-page table,
        # but the same "N." token could appear in a later financial table.
        # Keep the first hit (it's structurally inside the TOC) and skip
        # subsequent duplicates.
        if item_number in toc:
            i += 1
            continue
        # Look at next 1-3 lines for title + status
        title = ""
        status = "extracted"
        page_note = ""
        consumed = 1
        # Next line: title (or "Reserved" inline)
        if i + 1 < len(lines):
            next_pos, next_line = lines[i + 1]
            if reserved_re.match(next_line):
                # Title is literally "Reserved" (Item 6 post-2021 pattern)
                title = "Reserved"
                status = "reserved"
                consumed = 2
            elif item_num_re.match(next_line):
                # Skip — TOC row had no title/status (rare)
                consumed = 1
            else:
                title = next_line
                consumed = 2
                # Look at line after title for status indicator
                if i + 2 < len(lines):
                    after_title_pos, after_title = lines[i + 2]
                    if not_applicable_re.match(after_title):
                        status = "not_applicable"
                        page_note = after_title
                        consumed = 3
                    elif reserved_re.match(after_title):
                        status = "reserved"
                        page_note = after_title
                        consumed = 3
                    elif footnote_only_re.match(after_title):
                        # Footnote marker only — incorporated by reference
                        status = "incorporated_by_reference"
                        page_note = after_title
                        consumed = 3
                    elif page_range_re.match(after_title):
                        # Page range — usually means body section exists.
                        # Trailing * means part-incorporated-by-reference.
                        page_note = after_title
                        consumed = 3
                        if after_title.rstrip().endswith("*"):
                            # Mixed body + IBR — prefer extracted since
                            # there's a page range. The IBR is partial.
                            status = "extracted"
                    elif item_num_re.match(after_title):
                        # No status row — title was the whole entry
                        pass
                    elif len(after_title) < 80 and not after_title.lower().startswith("part "):
                        # Could be continuation of title or status note
                        # — keep cautiously
                        page_note = after_title
                        consumed = 3
        toc[item_number] = {
            "status": status,
            "page_note": page_note,
            "title": title,
            "toc_pos": line_pos,
        }
        i += consumed

    if toc:
        logger.info(
            "cover_toc_parsed",
            count=len(toc),
            items=sorted(toc.keys()),
            statuses={k: v["status"] for k, v in toc.items()},
        )
    return toc


def parse_end_cross_reference_index(text: str) -> dict[str, dict]:
    """Parse a Form 10-K Cross-Reference Index that some filers (Intel) put
    at the END of the document instead of (or in addition to) the cover-page
    TOC.

    Format observed in Intel 2026:

        Form 10-K Cross-Reference Index
        116

        Item 1.
        Business:
            General development of business    Pages 3-5, 18
            Description of business            Pages 3-24, 33

        Item 1A.
        Risk Factors                            Pages 37-51

        Item 1B.
        Unresolved Staff Comments               None

        Item 4.
        Mine Safety Disclosures                 None

        Item 6.
        [Reserved]

    For each item this parser captures: the page-reference string (or
    "None" / "[Reserved]") so we can mark status correctly for short
    items even when the body has no explicit heading.

    Returns mapping {item_number: {"status": str, "page_note": str,
    "title": str, "index_pos": int}}.
    """
    # Scan the END region (last 5% of doc).
    region_start = int(len(text) * 0.95)
    region = text[region_start:]
    # Pattern: 'Item N.\nTitle\nPages X-Y' or 'Item N.\nTitle\nNone'
    item_re = re.compile(
        r"(?im)^Item\s+(\d{1,2}[A-C]?)\.\s*\n+([^\n]{1,200})(?:\n+([^\n]{1,200}))?",
    )
    not_applicable_re = re.compile(r"(?i)^\s*(?:none|n\s*/?\s*a|not\s+applicable)\.?\s*$")
    reserved_re = re.compile(r"(?i)^\s*\[?\s*reserved\s*\]?\.?\s*$")
    page_range_re = re.compile(r"^\s*pages?\s+\d+|^\s*\d+\s*[\-–]\s*\d+", re.IGNORECASE)

    index: dict[str, dict] = {}
    for m in item_re.finditer(region):
        item_number = m.group(1).upper()
        if item_number not in _STANDARD_ITEM_NUMBERS:
            continue
        if item_number in index:
            continue
        title_or_status = (m.group(2) or "").strip()
        third_line = (m.group(3) or "").strip()
        # Determine status: title might be a status marker itself
        # (e.g., "[Reserved]" or "None"), or third line carries it.
        title = title_or_status
        if reserved_re.match(title_or_status):
            status = "reserved"
            title = "Reserved"
        elif not_applicable_re.match(title_or_status):
            status = "not_applicable"
        elif not_applicable_re.match(third_line):
            status = "not_applicable"
        elif reserved_re.match(third_line):
            status = "reserved"
        elif page_range_re.match(third_line) or "Pages" in third_line or re.match(r"^\d", third_line):
            # Body section exists — page reference here
            status = "extracted"
        elif "incorporat" in third_line.lower() or "proxy" in third_line.lower():
            status = "incorporated_by_reference"
        else:
            # Unclear — default to extracted (body section likely exists)
            status = "extracted"
        index[item_number] = {
            "status": status,
            "page_note": third_line[:120] if third_line else "",
            "title": title[:120],
            "index_pos": region_start + m.start(),
        }
    if index:
        logger.info(
            "end_cross_reference_parsed",
            count=len(index),
            statuses={k: v["status"] for k, v in index.items()},
        )
    return index


def detect_master_ibr_declaration(text: str) -> list[ItemBoundary]:
    """Detect the master 'Documents Incorporated by Reference' declaration.

    Many 10-Ks (especially banks/financials like Citigroup, IBM, etc.) put
    a single declaration on the cover page saying:

      "Portions of the registrant's proxy statement ... are incorporated
      by reference in this Form 10-K in response to Items 10, 11, 12, 13
      and 14 of Part III."

    The body doesn't have separate headings for those items — the
    declaration IS the entire incorporation reference. Without this
    detector, items 10-14 show as `not_found` even though they're
    legitimately incorporated by reference.

    This function:
      1. Searches the cover-page region (first 15% of doc) for the
         "incorporated by reference ... Items X, Y, Z" pattern
      2. Parses the item-number list
      3. Returns one ItemBoundary per declared item, all pointing to the
         master declaration position, with status_hint='incorporated_by_reference'

    Returns empty list if no master declaration found.
    """
    cover_zone = text[: int(len(text) * 0.15)] if len(text) > 1000 else text

    # Pattern matches "incorporated by reference ... Items 10, 11, 12, 13 and 14"
    # The intermediate text can be ~200 chars (filer mentions proxy statement,
    # annual meeting date, etc.). We anchor on the verb phrase first then look
    # for the item-number list in the trailing window.
    master_pattern = re.compile(
        r"(?is)\b(?:are|is)\s+incorporated\s+(?:herein\s+)?by\s+reference"
        r"[^.]{0,400}?items?\s+"
        r"(\d+(?:[A-C])?(?:\s*[,\s]+(?:and\s+)?\d+(?:[A-C])?)*)"
        r"\b",
    )
    boundaries: list[ItemBoundary] = []
    seen_items: set[str] = set()
    for m in master_pattern.finditer(cover_zone):
        item_list_str = m.group(1)
        # Parse "10, 11, 12, 13 and 14" → ["10", "11", "12", "13", "14"]
        item_numbers = re.findall(r"\d+[A-C]?", item_list_str)
        item_numbers = [n.upper() for n in item_numbers if n.upper() in _STANDARD_ITEM_NUMBERS]
        if not item_numbers:
            continue
        anchor_pos = m.start()
        # Capture the declaration text as the heading for these items
        # (truncated to a reasonable length)
        declaration_text = cover_zone[m.start():min(m.end() + 50, len(cover_zone))]
        declaration_text = " ".join(declaration_text.split())[:200]
        # Stagger start_pos by 1 char each to preserve stable ordering after
        # downstream sort. content_text will resolve to the master declaration
        # paragraph via the IBR status hint regardless of these tiny offsets.
        declaration_end = min(m.end() + 200, len(cover_zone))
        for offset, item_number in enumerate(item_numbers):
            if item_number in seen_items:
                continue
            seen_items.add(item_number)
            boundaries.append(
                ItemBoundary(
                    item_number=item_number,
                    start_pos=anchor_pos + offset,
                    end_pos=declaration_end,
                    heading_text=f"Item {item_number} (incorporated by reference from Proxy Statement)",
                    confidence=0.85,
                    source="master_ibr_declaration",
                    status_hint="incorporated_by_reference",
                )
            )
        if boundaries:
            logger.info(
                "master_ibr_detected",
                items=sorted(seen_items),
                pos=anchor_pos,
                text_preview=declaration_text[:120],
            )
            break  # only one master declaration per filing
    return boundaries


def _needs_title_fallback(boundaries: list[ItemBoundary], total_chars: int) -> bool:
    """Decide whether the regex-based pass missed the body and should be
    augmented (or replaced) by the title-only fallback.

    Three trip conditions, each captures a real failure mode observed
    against held-out 2026 filings:

    1. **Zero matches** (Citi 2026 pattern). The HTML uses bold-span
       title-only headings so no "Item N." text exists for the regex to
       find. We MUST fall back or downstream returns 22 NOT_FOUND
       placeholders.

    2. **End-of-doc cluster** (Intel 2026 pattern). Every match sits in
       the last 5% of the document. That's almost always a cover-page
       index / summary appendix, not real body sections — the body must
       be earlier. We replace the regex matches with title-fallback
       results in the body region.

    3. **All matches TOC-suspect** (the §2.2 single-match patch already
       handles half of this — when every regex match was downgraded to
       the TOC-suspect confidence floor, we have no real body anchors).
    """
    if not boundaries:
        return True
    if all(b.start_pos > total_chars * 0.95 for b in boundaries):
        return True
    if all(b.source == "heading_regex_toc_suspect" for b in boundaries):
        return True
    return False


def rule_based_parse(text: str, raw_html: str = "") -> ParseResult:
    """
    Stage 1: Rule-based parsing of 10-K text.

    Zero LLM cost. Combines THREE complementary detectors:
      1. Text regex detection (Pattern 1-4): catches standard "Item N. Title"
         format filings — works for ~70% of modern filings.
      2. Title-only fallback (text): catches filings whose body uses bold-
         span standalone titles (Citi 2026 / Intel 2026). Fires when
         `_needs_title_fallback` trip conditions are met.
      3. HTML-tag-aware extraction (when `raw_html` is provided): walks
         the raw HTML with BeautifulSoup, identifies heading-shaped
         elements (`<h1>`-`<h6>` / `<strong>` / CSS-styled-bold / ALL-CAPS
         spans), maps to item numbers via canonical title variants, and
         locates positions in normalized text. This is the structural-
         layer detector — sees what text-only detectors can't.

    Args:
        text: Normalized filing text (positions in returned boundaries
            refer to this string)
        raw_html: Raw HTML content BEFORE normalization. Optional but
            strongly recommended — without it, HTML-tag-aware detection
            can't run and filings like Citi 2026 lose half their anchors.

    Returns:
        ParseResult with detected boundaries and confidence scores
    """
    total_chars = len(text)

    # Step 1: Detect part boundaries
    part_boundaries = detect_part_boundaries(text)

    # Step 2: Detect item headings (regex-based)
    boundaries = detect_item_headings(text)
    used_title_fallback = False
    used_html_anchors = False

    # Step 2b: Title-only fallback for filings whose body uses bold-span
    # standalone titles (no "Item N." text — Citi 2026 / Intel 2026 / many
    # banking-layout XBRL filings). See _needs_title_fallback for the
    # trip conditions and rationale.
    if _needs_title_fallback(boundaries, total_chars):
        fallback = detect_item_headings_by_title(text)
        if fallback:
            used_title_fallback = True
            # Merge: keep any high-confidence regex matches that are NOT in
            # the suspicious zones; otherwise prefer the title-fallback
            # boundary (it's anchored to actual body content).
            regex_keep = [
                b for b in boundaries
                if b.source != "heading_regex_toc_suspect"
                and b.start_pos <= total_chars * 0.95
                and b.item_number not in {f.item_number for f in fallback}
            ]
            boundaries = sorted(regex_keep + fallback, key=lambda x: x.start_pos)
            logger.info(
                "title_fallback_activated",
                regex_kept=len(regex_keep),
                fallback_added=len(fallback),
                total=len(boundaries),
            )

    # Step 2bb-pre: End-of-doc Cross-Reference Index (Intel-style filings).
    # Some filers put the authoritative item index at the END of the doc,
    # not the cover page. Items appearing there with "None" / "[Reserved]"
    # / "Pages X-Y" tell us status when the body doesn't have an explicit
    # heading. We use this as a SECONDARY status source — body anchors
    # still win when present.
    end_index_map = parse_end_cross_reference_index(text)
    if end_index_map:
        end_added = 0
        for item_number, info in end_index_map.items():
            # No existence check — emit always. The dedupe in
            # _build_items picks the best boundary per item, preferring
            # body anchors with longer content over short cross-reference
            # entries. Short cross-ref entries serve as fallback when the
            # body has no detectable heading.
            boundaries.append(
                ItemBoundary(
                    item_number=item_number,
                    start_pos=info["index_pos"],
                    end_pos=info["index_pos"] + 300,
                    heading_text=info["title"] or f"Item {item_number}",
                    confidence=0.80,
                    source="end_cross_reference",
                    status_hint=info["status"],
                )
            )
            end_added += 1
        if end_added:
            boundaries.sort(key=lambda b: b.start_pos)
            logger.info("end_cross_reference_merged", added=end_added)

    # Step 2ba: Cover-page TOC table as authoritative status source.
    # Citi/IBM-style 10-Ks have a TOC table on the cover page showing each
    # Item's status (page range vs "Not Applicable" vs "Reserved" vs
    # footnote-only IBR). Items that don't have body sections — but ARE
    # legitimately "Not Applicable" or "Reserved" or "Incorporated by
    # Reference" — should still appear in the result with the correct
    # status. Without this detector, those items show as not_found.
    #
    # We emit a boundary for EVERY TOC-listed item that isn't already
    # found. For "extracted" status items, the dedupe step in pipeline's
    # _build_items will prefer the body boundary when one exists; if no
    # body boundary is found, the TOC entry becomes the content_text
    # (preserves the page-range reference like "287-293" so callers know
    # the item is acknowledged even when the heading style defeats body
    # detection).
    toc_status_map = parse_cover_toc_table(text)
    if toc_status_map:
        toc_only_added = 0
        for item_number, info in toc_status_map.items():
            # No existence check — emit always. The dedupe in
            # _build_items picks the best per item, preferring body
            # anchors with longer content over the short TOC entry.
            boundaries.append(
                ItemBoundary(
                    item_number=item_number,
                    start_pos=info["toc_pos"],
                    end_pos=info["toc_pos"] + 200,  # short content window
                    heading_text=info["title"] or f"Item {item_number}",
                    confidence=0.85,
                    source="cover_toc_status",
                    status_hint=info["status"],
                )
            )
            toc_only_added += 1
        if toc_only_added:
            boundaries.sort(key=lambda b: b.start_pos)
            logger.info("cover_toc_status_merged", added=toc_only_added)

    # Step 2bb: Master "Documents Incorporated by Reference" declaration.
    # Many financial-services 10-Ks (Citi, banks) state on the cover page
    # that Items 10–14 are incorporated by reference — and never include
    # separate body headings for those items. Without this detector,
    # those items show as not_found even though they're legitimately IBR.
    master_ibr = detect_master_ibr_declaration(text)
    if master_ibr:
        # Always merge — dedupe in _build_items picks best per item.
        boundaries.extend(master_ibr)
        boundaries.sort(key=lambda b: b.start_pos)
        logger.info("master_ibr_merged", added=len(master_ibr))

    # Step 2c: HTML-tag-aware extraction (when raw HTML available).
    # Adds anchors for items that text-only detection missed — works for
    # Citi 2026 (bold spans), Intel 2026 (styled-color spans), and any
    # other filer using structural heading markup.
    if raw_html:
        try:
            from src.task3_sec.html_heading_extractor import detect_html_anchors

            html_anchors = detect_html_anchors(raw_html, text)
            if html_anchors:
                added = 0
                for a in html_anchors:
                    boundaries.append(
                        ItemBoundary(
                            item_number=a["item_number"],
                            start_pos=a["start_pos"],
                            heading_text=a["heading_text"],
                            # 0.80 — HTML structural detection is more
                            # reliable than text title-fallback (0.55-0.70)
                            # but slightly less than regex+TOC-confirmed
                            # multi-match (0.90-0.95).
                            confidence=0.80,
                            source="html_anchor",
                        )
                    )
                    added += 1
                if added:
                    used_html_anchors = True
                    boundaries.sort(key=lambda b: b.start_pos)
                    logger.info("html_anchors_merged", added=added, total=len(boundaries))
        except Exception as e:
            logger.warning("html_anchor_step_failed", err=str(e)[:160])

    # Step 3: Set end positions (each item ends where the next begins),
    # EXCEPT for cover-page-anchored boundaries (master_ibr / cover_toc_status)
    # which point to short cover-page snippets and keep their pre-set end_pos.
    _cover_page_sources = {"master_ibr_declaration", "cover_toc_status", "end_cross_reference"}
    for i, boundary in enumerate(boundaries):
        if boundary.source in _cover_page_sources and boundary.end_pos > 0:
            continue  # preserve the cover-page content window
        if i + 1 < len(boundaries):
            next_b = boundaries[i + 1]
            # If next boundary is cover-page-anchored at a similar position,
            # don't terminate at that — find the next BODY boundary instead.
            if next_b.source in _cover_page_sources:
                next_real = None
                for j in range(i + 1, len(boundaries)):
                    if boundaries[j].source not in _cover_page_sources:
                        next_real = boundaries[j]
                        break
                boundary.end_pos = next_real.start_pos if next_real else total_chars
            else:
                boundary.end_pos = next_b.start_pos
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
        used_title_fallback=used_title_fallback,
        used_html_anchors=used_html_anchors,
    )

    return result
