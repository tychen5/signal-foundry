"""
HTML/Text Normalizer for SEC 10-K Filings.

Handles the enormous format variation in SEC filings:
- Modern inline XBRL HTML (post-2020)
- Standard HTML (2005-2020)
- Plain text filings (pre-2005)
- Mixed formats with embedded tables

Produces clean normalized text while preserving char positions for char_range mapping.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Comment, NavigableString

from src.shared.logger import get_logger

logger = get_logger("normalizer")


def detect_format(content: str) -> str:
    """
    Detect the filing format.

    Returns:
        "xbrl_html" | "html" | "text"
    """
    content_lower = content[:5000].lower()
    if "ix:nonnumeric" in content_lower or "ix:nonfraction" in content_lower:
        return "xbrl_html"
    elif "<html" in content_lower or "<body" in content_lower:
        return "html"
    else:
        return "text"


def normalize_filing(content: str) -> tuple[str, str]:
    """
    Normalize a SEC filing to clean text.

    Args:
        content: Raw filing content (HTML or text)

    Returns:
        Tuple of (normalized_text, format_type)
    """
    fmt = detect_format(content)
    logger.info("normalizing_filing", format=fmt, raw_chars=len(content))

    if fmt in ("xbrl_html", "html"):
        normalized = _normalize_html(content)
    else:
        normalized = _normalize_text(content)

    logger.info("normalization_complete", format=fmt, normalized_chars=len(normalized))
    return normalized, fmt


def _normalize_html(html_content: str) -> str:
    """
    Normalize HTML filing to clean text preserving structure.

    Strategy:
    1. Parse with BeautifulSoup (lxml parser for speed)
    2. Remove noise elements (scripts, styles, hidden divs, XBRL headers)
    3. Convert block elements to newlines
    4. Preserve meaningful whitespace for heading detection
    """
    try:
        soup = BeautifulSoup(html_content, "lxml")
    except Exception:
        soup = BeautifulSoup(html_content, "html.parser")

    # Remove noise elements
    for tag in soup.find_all(["script", "style", "meta", "link"]):
        tag.decompose()

    # Remove hidden XBRL header blocks
    for tag in soup.find_all("ix:header"):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove hidden display:none divs (XBRL wrapper cruft)
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        tag.decompose()

    # Process the document
    lines: list[str] = []
    _extract_text_recursive(soup.body or soup, lines)

    text = "\n".join(lines)

    # Clean up excessive whitespace while preserving structure
    text = re.sub(r"\n{4,}", "\n\n\n", text)  # Max 3 newlines
    text = re.sub(r"[ \t]{2,}", " ", text)  # Collapse spaces
    text = re.sub(r" +\n", "\n", text)  # Trailing spaces
    text = re.sub(r"\n +", "\n", text)  # Leading spaces on lines

    return text.strip()


def _extract_text_recursive(element, lines: list[str]) -> None:
    """Recursively extract text from HTML, converting block elements to newlines."""
    block_tags = {
        "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "tr", "table", "li", "ol", "ul", "blockquote",
        "section", "article", "header", "footer", "main",
        "br", "hr",
    }

    if isinstance(element, NavigableString):
        text = str(element).strip()
        if text:
            lines.append(text)
        return

    tag_name = getattr(element, "name", None)
    if tag_name is None:
        return

    # Skip decomposed elements
    if tag_name in ("script", "style"):
        return

    # Add newline before block elements
    if tag_name in block_tags:
        lines.append("")

    for child in element.children:
        _extract_text_recursive(child, lines)

    # Add newline after block elements
    if tag_name in block_tags:
        lines.append("")


def _normalize_text(text_content: str) -> str:
    """
    Normalize plain text filing (pre-2005 format).

    These are simpler but have their own challenges:
    - Form feed characters (\\x0c) as page separators
    - Fixed-width formatting with lots of spaces
    - Headers/footers repeated on each page
    """
    # Remove form feed characters (page breaks)
    text = text_content.replace("\x0c", "\n\n")

    # Remove common header/footer patterns
    text = re.sub(
        r"(?m)^-{20,}$",  # Long dashes as separators
        "\n",
        text,
    )

    # Clean up excessive whitespace
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip()


def extract_table_of_contents(normalized_text: str) -> list[dict]:
    """
    Extract Table of Contents entries from normalized text.

    Many 10-K filings have a ToC section listing items with page numbers.
    This provides initial item position hints.

    Returns:
        List of dicts with item_number, title, and approximate position
    """
    toc_entries = []

    # Find ToC section (usually in the first 10% of the document)
    toc_search_region = normalized_text[: len(normalized_text) // 5]

    # Pattern: "Item 1. Business" or "ITEM 1A. Risk Factors" (with optional page numbers)
    toc_pattern = re.compile(
        r"(?i)(item)\s+(\d+[a-c]?)\s*[\.\:\—\-\s]+"
        r"([A-Z][^\n\d]{3,80}?)"
        r"(?:\s*\.{2,}\s*(\d+))?"  # Optional page number
        r"\s*$",
        re.MULTILINE,
    )

    for match in toc_pattern.finditer(toc_search_region):
        entry = {
            "item_number": match.group(2).upper(),
            "title": match.group(3).strip().rstrip("."),
            "position_hint": match.start(),
            "source": "toc",
        }
        toc_entries.append(entry)

    logger.info("toc_extracted", entries=len(toc_entries))
    return toc_entries
