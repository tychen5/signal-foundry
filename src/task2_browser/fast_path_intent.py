"""
Intent parser for the static-site fast path.

Why this exists: the original fast path used per-domain handlers each with
their own ad-hoc keyword matching. That broke on small phrasing variations
("second paragraph" instead of "first paragraph", "authors of the paper"
treated as wanting both title and authors, etc.) and didn't generalize to
new domains.

This module is the single source of truth for what the user *wants* — a
domain-agnostic structured `Intent` that handlers consume. The intent
parser is pure (no IO), unit-testable, and shared across every handler.

Intent dimensions:

  - **Paragraph index** ("first paragraph", "2nd paragraph", "last paragraph")
  - **Paragraph range** ("first 3 paragraphs", "paragraphs 2-4")
  - **Field selection** ("authors only", "just the title", "abstract and authors")
  - **Top-N collection** ("top 5 stories", "first 3 results")
  - **Summary/definition intents** ("what is X", "tell me about X", "define X")

Handlers query the intent (e.g. `intent.wants_only_field("authors")`) to
decide what to return — this gives strict-mode field selection (no
over-answering) and flexible paragraph navigation across any text-heavy
static site (Wikipedia, MDN, blog posts, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ASCII + named ordinals up to 20th (covers the realistic range; we rarely
# extract paragraph 20+ in practice).
_ORDINAL_WORDS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
    "eleventh": 11, "11th": 11,
    "twelfth": 12, "12th": 12,
    "13th": 13, "14th": 14, "15th": 15, "16th": 16,
    "17th": 17, "18th": 18, "19th": 19, "20th": 20,
}
_CARDINAL_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Common field-name synonyms by canonical key. Handlers use canonical keys.
_FIELD_SYNONYMS: dict[str, list[str]] = {
    "title": ["title", "headline", "name of the paper", "paper name", "paper title"],
    "author": ["author", "authors", "contributor", "contributors", "by whom", "written by"],
    "abstract": ["abstract", "summary", "synopsis", "tl;dr", "tldr"],
    "date": ["date", "published", "publication date", "release date", "when was"],
    "version": ["version", "release", "tag", "latest"],
    "description": ["description", "what it does", "what is it"],
    "category": ["category", "categories", "topics", "subjects"],
    "license": ["license", "licensed under"],
    "url": ["url", "link", "permalink"],
    "comments": ["comment", "comments", "comment count"],
    "points": ["points", "score", "upvotes", "votes"],
    "headline": ["headline", "top story", "first story", "first post",
                 "first headline", "top headline", "top post"],
}


@dataclass
class Intent:
    """Structured user intent for fast-path handlers.

    All fields default to "no specific request" so handlers can fall back
    cleanly to their domain default when the user's task is generic.
    """
    # Paragraph navigation (text-heavy pages)
    paragraph_index: Optional[int] = None  # 1-based; -1 = last
    paragraph_range: Optional[tuple[int, int]] = None  # inclusive 1-based
    paragraphs_all: bool = False
    wants_summary: bool = False
    wants_definition: bool = False

    # Field selection (structured-data pages)
    requested_fields: set[str] = field(default_factory=set)
    # When True the handler must NOT over-answer — only return requested_fields.
    # When False the handler MAY include reasonable defaults if no field is
    # explicitly requested.
    strict_field_mode: bool = False

    # Top-N / list selection
    top_n: Optional[int] = None

    # Generic flags
    raw_task: str = ""

    def wants_only(self, *fields: str) -> bool:
        """True iff strict mode AND requested_fields is exactly {*fields}."""
        return self.strict_field_mode and self.requested_fields == set(fields)

    def wants(self, field_name: str) -> bool:
        """True iff this field was explicitly requested."""
        return field_name in self.requested_fields

    def any_paragraph_request(self) -> bool:
        return (
            self.paragraph_index is not None
            or self.paragraph_range is not None
            or self.paragraphs_all
            or self.wants_summary
            or self.wants_definition
        )

    def any_field_request(self) -> bool:
        return bool(self.requested_fields)


# Regex patterns — precompiled for performance and pinned for clarity.
# Word-boundary anchored; case-insensitive applied at compile.
_RE_PARAGRAPH_LAST = re.compile(
    r"\b(?:the\s+)?last\s+paragraph\b", re.IGNORECASE,
)
_RE_PARAGRAPH_ALL = re.compile(
    r"\b(?:the\s+)?(?:whole\s+article|full\s+article|entire\s+article|"
    r"all\s+paragraphs|every\s+paragraph|full\s+text)\b",
    re.IGNORECASE,
)
_RE_PARAGRAPH_RANGE = re.compile(
    r"\bparagraphs?\s+(\d{1,2})\s*(?:to|-|–|—|through|thru)\s*(\d{1,2})\b",
    re.IGNORECASE,
)
_RE_PARAGRAPH_FIRST_N = re.compile(
    r"\b(?:the\s+)?first\s+(\d{1,2})\s+paragraphs?\b", re.IGNORECASE,
)
_RE_PARAGRAPH_ORDINAL = re.compile(
    r"\b(?:the\s+)?("
    + "|".join(re.escape(w) for w in _ORDINAL_WORDS)
    + r")\s+paragraph\b",
    re.IGNORECASE,
)
_RE_PARAGRAPH_NUMBERED = re.compile(
    r"\bparagraph\s*(?:number\s*)?#?\s*(\d{1,2})\b", re.IGNORECASE,
)
_RE_PARAGRAPH_SINGULAR = re.compile(
    r"\b(?:the\s+)?(?:first|opening|lead|introductory|intro)\s+paragraph\b",
    re.IGNORECASE,
)
_RE_LEAD_SECTION = re.compile(
    r"\b(?:the\s+)?(?:lead\s+section|introduction\s+paragraph|"
    r"introduction|introductory\s+text|opening\s+paragraph|opening\s+lines)\b",
    re.IGNORECASE,
)
_RE_SUMMARY = re.compile(
    r"\b(?:summary|summari[sz]e|tl;?dr|gist|brief\s+overview|overview|"
    r"tell\s+me\s+about|describe|what\s+(?:is|are|does)|what's|"
    r"give\s+me\s+a\s+(?:summary|brief))\b",
    re.IGNORECASE,
)
_RE_DEFINITION = re.compile(
    r"\b(?:define|definition\s+of|meaning\s+of|what\s+does\s+[a-z]+\s+mean)\b",
    re.IGNORECASE,
)
_RE_TOP_N = re.compile(
    r"\b(?:top|first|leading|best)\s+(\d{1,2})\b", re.IGNORECASE,
)

# CJK readers
_RE_CJK_PARAGRAPH_FIRST = re.compile(r"首段|首段落|第一段")
_RE_CJK_SUMMARY = re.compile(r"簡介|介紹|介绍|概述|什麼是|是什麼|什么是|是什么")


def parse_intent(task: str) -> Intent:
    """Parse a natural-language task into a structured Intent.

    The parser is liberal about matching — false positives (intent set when
    user didn't explicitly say so) are OK because the handlers still get
    to refuse. False negatives (intent missed when user did ask) are worse
    because they cause fall-through to the expensive agent path.

    Field detection uses synonym lookup — each canonical field has multiple
    natural-language variants (e.g. "author" / "authors" / "by whom" /
    "written by" all map to canonical "author").
    """
    intent = Intent(raw_task=task)
    if not task:
        return intent
    task_lower = task.lower()

    # ── Paragraph navigation ──────────────────────────────────────────
    # Order matters: most specific first.
    if _RE_PARAGRAPH_ALL.search(task_lower):
        intent.paragraphs_all = True
    elif _RE_PARAGRAPH_LAST.search(task_lower):
        intent.paragraph_index = -1
    elif (m := _RE_PARAGRAPH_RANGE.search(task_lower)):
        a, b = int(m.group(1)), int(m.group(2))
        intent.paragraph_range = (min(a, b), max(a, b))
    elif (m := _RE_PARAGRAPH_FIRST_N.search(task_lower)):
        n = int(m.group(1))
        if n > 0:
            intent.paragraph_range = (1, n)
    elif (m := _RE_PARAGRAPH_ORDINAL.search(task_lower)):
        word = m.group(1).lower()
        intent.paragraph_index = _ORDINAL_WORDS[word]
    elif (m := _RE_PARAGRAPH_NUMBERED.search(task_lower)):
        intent.paragraph_index = int(m.group(1))
    elif _RE_PARAGRAPH_SINGULAR.search(task_lower):
        intent.paragraph_index = 1
    elif _RE_LEAD_SECTION.search(task_lower):
        intent.paragraph_index = 1
    elif _RE_CJK_PARAGRAPH_FIRST.search(task):
        intent.paragraph_index = 1

    # ── Summary / definition intents ─────────────────────────────────
    if _RE_SUMMARY.search(task_lower) or _RE_CJK_SUMMARY.search(task):
        intent.wants_summary = True
    if _RE_DEFINITION.search(task_lower):
        intent.wants_definition = True

    # ── Top-N detection ──────────────────────────────────────────────
    if (m := _RE_TOP_N.search(task_lower)):
        try:
            intent.top_n = int(m.group(1))
        except (ValueError, TypeError):
            pass

    # ── Field detection (strict mode if user says "only" / "just") ──
    explicitly_only = bool(re.search(
        r"\b(?:only|just|nothing\s+but|merely|solely)\b",
        task_lower,
    ))
    for canonical, synonyms in _FIELD_SYNONYMS.items():
        for syn in synonyms:
            # Word boundaries unless synonym contains punctuation/space
            if " " in syn or any(c in syn for c in (";", "/")):
                if syn in task_lower:
                    intent.requested_fields.add(canonical)
                    break
            else:
                if re.search(rf"\b{re.escape(syn)}\b", task_lower):
                    intent.requested_fields.add(canonical)
                    break

    # When the user names a SINGLE specific field, that beats generic
    # summary/definition intent — phrases like "what are the authors of X"
    # trip `_RE_SUMMARY` on "what" but the real intent is the named field.
    # Suppress summary/definition AND enable strict mode.
    single_field_request = (
        len(intent.requested_fields) == 1
        and intent.paragraph_index is None
        and intent.paragraph_range is None
        and not intent.paragraphs_all
    )
    if single_field_request:
        intent.wants_summary = False
        intent.wants_definition = False
        intent.strict_field_mode = True

    # Strict mode: user explicitly limited the request ("only", "just")
    # wins regardless.
    if explicitly_only:
        intent.strict_field_mode = True

    return intent
