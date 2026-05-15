"""
HTML-tag-aware heading extractor for SEC 10-K filings.

Why this exists: the text-based `rule_parser` operates on normalized text
that has lost ALL HTML structure. For filings like Citi 2026 / Intel 2026
that render section headings as bold spans / styled paragraphs WITHOUT
literal "Item N." text, the text-only path is blind.

This module walks the **raw HTML** with BeautifulSoup and identifies
heading-like elements by:

  - Tag: `<h1>` / `<h2>` / `<h3>` / `<h4>`
  - Inline strong/bold: `<strong>` / `<b>` with substantial text
  - CSS-styled bold: `<span>` / `<p>` / `<td>` / `<div>` whose style
    contains `font-weight: 700` / `font-weight: bold`
  - ALL-CAPS text content (banking-layout filings render headings as
    `RISK FACTORS` / `DISCLOSURE CONTROLS AND PROCEDURES` in CSS-styled
    bold spans)

Each candidate heading is then matched against `ITEM_TITLE_VARIANTS` to
determine the item number, and its position is mapped back to the
NORMALIZED text by content-prefix search.

The result is high-confidence (`0.80`) boundaries that supplement the
text-based rule parser.

Added 2026-05-15 as the larger lift in response to interviewer review:
Citi 2026 has 0 "ITEM 1" text in raw HTML, Intel 2026 hides its body
headings in styled spans. This is the structural-layer detector the
text-only parser couldn't be.
"""

from __future__ import annotations

import re
import warnings
from typing import Optional

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from src.shared.logger import get_logger
from src.task3_sec.schemas import ITEM_TITLE_VARIANTS, STANDARD_10K_ITEMS

logger = get_logger("html_heading_extractor")

# Tags that are structurally headings.
_STRUCTURAL_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Tags that MIGHT be a heading when CSS-styled bold / their content is short.
_CANDIDATE_HEADING_TAGS = {"strong", "b", "span", "p", "td", "div", "font"}

# CSS hint patterns indicating a styled-bold heading.
_BOLD_STYLE_RE = re.compile(r"font-weight\s*:\s*(?:bold|[6789]\d\d|1000)", re.IGNORECASE)

# Cap candidate heading text length — actual headings are short prose.
# Anything over 200 chars is almost certainly body content with a bold
# emphasis somewhere inside, not a section heading.
_MAX_HEADING_LEN = 200
_MIN_HEADING_LEN = 4

# Build a reverse map: lowered-title-variant → item_number.
# Order matters — longer / more specific variants must win over shorter
# substrings (so "disclosure controls and procedures" beats bare
# "controls and procedures").
def _build_title_index() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    # Standard item titles (full canonical names)
    for it in STANDARD_10K_ITEMS:
        pairs.append((it["item_title"].lower(), it["item_number"]))
    # Variant titles (short / colloquial forms)
    for item_number, variants in ITEM_TITLE_VARIANTS.items():
        for v in variants:
            pairs.append((v.lower(), item_number))
    # Filer-specific body-heading variants we've seen in 2026 filings
    extras: list[tuple[str, str]] = [
        ("our business", "1"),
        ("disclosure controls and procedures", "9A"),
        ("consolidated financial statements", "8"),
        ("market for the registrant's common equity", "5"),
        ("changes in and disagreements with accountants on accounting and financial disclosure", "9"),
        ("changes in and disagreements with accountants", "9"),
        ("management's discussion and analysis of financial condition and results of operations", "7"),
        ("management's discussion and analysis", "7"),
        ("quantitative and qualitative disclosures about market risk", "7A"),
        ("directors, executive officers and corporate governance", "10"),
        ("directors, executive officers, and corporate governance", "10"),
        ("security ownership of certain beneficial owners and management", "12"),
        ("certain relationships and related transactions, and director independence", "13"),
        ("certain relationships and related transactions", "13"),
        ("principal accountant fees and services", "14"),
        ("principal accounting fees and services", "14"),
        ("exhibits and financial statement schedules", "15"),
        ("form 10-k summary", "16"),
        ("mine safety disclosures", "4"),
        ("unresolved staff comments", "1B"),
        ("risk factors", "1A"),
        ("cybersecurity", "1C"),
        ("legal proceedings", "3"),
        ("properties", "2"),
        ("controls and procedures", "9A"),
        ("other information", "9B"),
        ("disclosure regarding foreign jurisdictions that prevent inspections", "9C"),
        ("foreign jurisdictions that prevent inspections", "9C"),
        ("executive compensation", "11"),
        ("selected financial data", "6"),
        ("business", "1"),  # last — most ambiguous
    ]
    pairs.extend(extras)
    # Deduplicate while preserving order, then sort longest-first so the
    # match loop picks the most specific variant.
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for title, num in pairs:
        if title in seen:
            continue
        seen.add(title)
        deduped.append((title, num))
    deduped.sort(key=lambda p: -len(p[0]))
    return deduped


_TITLE_INDEX = _build_title_index()


def _match_item_number(heading_text: str) -> Optional[tuple[str, str]]:
    """Return (item_number, canonical_title) if the heading text matches a
    known item title variant. None otherwise.

    Matching strategy:
      1. Normalize whitespace, strip outer punctuation, lower-case
      2. Try EXACT match against indexed variants (longest-first)
      3. Try PREFIX match (heading starts with a known variant)
      4. Try CONTAINS match for short heading text only

    Heading text is allowed to be wrapped in "Item N. " prefix — we strip
    that before matching since the HTML structure already tells us this
    is a heading.
    """
    if not heading_text:
        return None
    norm = " ".join(heading_text.lower().split())
    norm = norm.strip(" .:;,—-")
    # Strip leading "item N." / "item NA." prefix
    norm = re.sub(r"^item\s+\d+[a-c]?\s*[.:—-]*\s*", "", norm)
    norm = norm.strip()
    if not norm or len(norm) > _MAX_HEADING_LEN:
        return None
    for variant, item_number in _TITLE_INDEX:
        if norm == variant:
            return item_number, variant
    for variant, item_number in _TITLE_INDEX:
        if norm.startswith(variant) and len(norm) <= len(variant) + 30:
            return item_number, variant
    for variant, item_number in _TITLE_INDEX:
        if len(norm) <= len(variant) + 50 and variant in norm:
            # only allow contained-match when variant is reasonably long
            if len(variant) >= 12:
                return item_number, variant
    return None


def _is_likely_heading_element(elem) -> bool:
    """Decide whether a BeautifulSoup element is heading-shaped.

    Conditions (any one suffices):
      - Structural heading tag (`<h1>`-`<h6>`)
      - Tag in candidate set AND has bold-style CSS
      - Tag in candidate set AND text is ALL-CAPS short prose
      - Tag is `<strong>` / `<b>`

    Excludes elements whose text is very long (body prose).
    """
    if elem is None or not hasattr(elem, "name") or elem.name is None:
        return False
    tag = elem.name.lower()
    if tag in _STRUCTURAL_HEADING_TAGS:
        return True
    if tag not in _CANDIDATE_HEADING_TAGS:
        return False
    # Get visible text — bounded
    try:
        text = elem.get_text(" ", strip=True)
    except Exception:
        return False
    if not text:
        return False
    length = len(text)
    if length < _MIN_HEADING_LEN or length > _MAX_HEADING_LEN:
        return False
    # ALL CAPS short prose
    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters and letters.isupper() and length <= 120:
        return True
    # CSS-styled bold
    style = (elem.get("style") or "") if hasattr(elem, "get") else ""
    if _BOLD_STYLE_RE.search(style):
        return True
    # `<strong>` / `<b>` is intrinsically bold
    if tag in {"strong", "b"}:
        return True
    return False


def extract_heading_candidates_from_html(raw_html: str) -> list[dict]:
    """Walk raw HTML and return heading-shaped candidates with text content.

    Returns a list of dicts:
        {"text": <heading text>, "tag": <tag>, "doc_offset": <approx>}

    `doc_offset` is the approximate character position in the RAW HTML
    where this element starts — used downstream to anchor candidates in
    document order (and to sort overlapping candidates).
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(raw_html, "lxml")
    except Exception:
        soup = BeautifulSoup(raw_html, "html.parser")

    # Strip noise tags up-front.
    for tag in soup.find_all(["script", "style", "meta", "link", "ix:header"]):
        tag.decompose()

    candidates: list[dict] = []
    for elem in soup.find_all(True):
        if not _is_likely_heading_element(elem):
            continue
        try:
            text = elem.get_text(" ", strip=True)
        except Exception:
            continue
        if not text:
            continue
        # Collapse multiple spaces
        text = " ".join(text.split())
        if len(text) < _MIN_HEADING_LEN or len(text) > _MAX_HEADING_LEN:
            continue
        candidates.append(
            {
                "text": text,
                "tag": elem.name.lower(),
                # Approximate raw-HTML position via string method (cheap,
                # we don't need exact offsets — they're only used for
                # relative ordering of candidates).
                "doc_offset": _approx_raw_pos(raw_html, str(elem)[:200]),
            }
        )
    logger.info("html_heading_candidates_extracted", count=len(candidates))
    return candidates


def _approx_raw_pos(raw: str, fragment_prefix: str) -> int:
    """Cheap raw-HTML position estimate — best-effort substring search."""
    if not fragment_prefix:
        return -1
    try:
        return raw.index(fragment_prefix)
    except (ValueError, TypeError):
        return -1


def match_candidates_to_items(
    candidates: list[dict],
    normalized_text: str,
    body_start_pct: float = 0.10,
    body_end_pct: float = 0.92,
) -> list[dict]:
    """For each HTML candidate, attempt to (a) match to an item number via
    title-variant lookup, and (b) locate the heading's position in the
    NORMALIZED text (so downstream code can slice content_text and
    char_range from `normalized_text`).

    The position-mapping step is critical: BeautifulSoup gave us text from
    raw HTML, but the pipeline operates on normalized text. We search for
    ALL occurrences of the candidate text inside normalized_text (within
    the body region), and pick the BEST body-region occurrence using:

      - Skip the TOC zone (`< body_start_pct`)
      - Skip the end-index zone (`> body_end_pct`)
      - Among the remaining occurrences, prefer the LATEST one — TOC
        entries appear first in document order, body sections later
      - But cap "latest": if the latest is the only late occurrence and
        sits in the last 10% of body, prefer an earlier mid-doc match
        if there are >1 candidates

    Returns:
        Sorted list of {"item_number", "title", "start_pos", "heading_text"}
    """
    doc_len = len(normalized_text)
    body_floor = int(doc_len * body_start_pct)
    body_ceil = int(doc_len * body_end_pct)

    anchors_by_item: dict[str, dict] = {}
    for cand in candidates:
        match = _match_item_number(cand["text"])
        if not match:
            continue
        item_number, variant = match
        # Find ALL body-region occurrences of this candidate's text.
        positions = _locate_all_in_normalized(
            normalized_text,
            cand["text"],
            body_floor,
            body_ceil,
        )
        if not positions:
            positions = _locate_all_in_normalized(
                normalized_text,
                variant,
                body_floor,
                body_ceil,
            )
        if not positions:
            continue
        # Pick the best body position. Heuristic: skip leading positions
        # that are within the first 12% of doc (often a forward TOC
        # reference disguised as a body heading). Among remaining, take
        # the FIRST — body sections proper start after the TOC zone.
        toc_zone_end = int(doc_len * 0.12)
        body_positions = [p for p in positions if p >= toc_zone_end]
        if not body_positions:
            body_positions = positions
        best_pos = body_positions[0]
        # Keep best per item — prefer LATER position only if it's
        # substantially better-anchored (gives us robustness against TOC
        # forward-references). We compare by position depth in doc.
        if item_number not in anchors_by_item or best_pos < anchors_by_item[item_number]["start_pos"]:
            anchors_by_item[item_number] = {
                "item_number": item_number,
                "title": cand["text"],
                "start_pos": best_pos,
                "heading_text": cand["text"],
                "matched_variant": variant,
                "html_tag": cand["tag"],
                "all_positions": positions,
            }
    anchors = sorted(anchors_by_item.values(), key=lambda a: a["start_pos"])
    logger.info(
        "html_anchors_matched",
        count=len(anchors),
        items=[a["item_number"] for a in anchors],
    )
    return anchors


def _locate_all_in_normalized(
    text: str,
    needle: str,
    body_floor: int,
    body_ceil: int,
) -> list[int]:
    """Return all positions where `needle` appears in `text` within the
    body region. Case-insensitive."""
    if not needle:
        return []
    positions: list[int] = []
    norm_needle = " ".join(needle.split())
    lower_text = text.lower()
    lower_needle = norm_needle.lower()
    start = body_floor
    while True:
        idx = lower_text.find(lower_needle, start)
        if idx == -1 or idx >= body_ceil:
            break
        positions.append(idx)
        start = idx + len(lower_needle)
    return positions


def _locate_in_normalized(
    text: str,
    needle: str,
    body_floor: int,
    body_ceil: int,
) -> Optional[int]:
    """Find the FIRST occurrence of `needle` (case-insensitive) in `text`
    within `[body_floor, body_ceil]`. Returns position or None."""
    if not needle:
        return None
    # Try exact case first (preserves ALL CAPS specificity)
    idx = text.find(needle, body_floor)
    if idx != -1 and idx < body_ceil:
        return idx
    # Try case-insensitive
    lower_text = text.lower()
    lower_needle = needle.lower()
    idx = lower_text.find(lower_needle, body_floor)
    if idx != -1 and idx < body_ceil:
        return idx
    # Try with whitespace normalization
    norm_needle = " ".join(needle.split())
    if norm_needle != needle:
        idx = text.find(norm_needle, body_floor)
        if idx != -1 and idx < body_ceil:
            return idx
    return None


def detect_html_anchors(
    raw_html: str,
    normalized_text: str,
    body_start_pct: float = 0.05,
    body_end_pct: float = 0.95,
) -> list[dict]:
    """One-shot entry point: raw HTML + normalized text → ordered anchor
    list of {item_number, title, start_pos, heading_text}.

    Args:
        raw_html: Raw HTML content (BEFORE normalization)
        normalized_text: Normalized text (positions in returned anchors
            refer to this string)
        body_start_pct: Skip first N% of doc (TOC zone)
        body_end_pct: Skip last (1 - N)% of doc (end-index appendix)

    Returns: anchors sorted by start_pos.

    Returns empty list on any failure — caller falls through to existing
    text-only detection.
    """
    if not raw_html or not normalized_text:
        return []
    try:
        candidates = extract_heading_candidates_from_html(raw_html)
        if not candidates:
            return []
        return match_candidates_to_items(
            candidates,
            normalized_text,
            body_start_pct=body_start_pct,
            body_end_pct=body_end_pct,
        )
    except Exception as e:
        logger.warning("html_anchor_extraction_failed", err=str(e)[:160])
        return []
