"""Cross-provider helpers for working with LangChain chat-model responses."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# Smart-quote / Unicode artifacts the JSON extractor must normalise. LLMs
# (especially via OpenRouter) occasionally inject these, breaking strict
# json.loads. List is intentionally short — over-aggressive normalisation
# would mangle real content.
_JSON_NORMALISE = (
    ("“", '"'),  # left double curly
    ("”", '"'),  # right double curly
    ("‘", "'"),  # left single curly
    ("’", "'"),  # right single curly
    (" ", " "),  # NBSP — invalid as JSON whitespace in some parsers
)


def extract_json_object(raw: Any) -> Optional[dict]:
    """Best-effort JSON-object extractor for LLM responses.

    Real-world LLM responses fail strict json.loads in many ways:
      • ```json fenced code blocks (with or without language tag)
      • Leading prose ("Here is the JSON: { ... }")
      • Trailing prose ("This represents..." after the JSON)
      • Smart quotes from copy-paste-style models
      • Chinese full-width punctuation in commentary
      • Final non-JSON line ("Confidence: HIGH")

    Strategy: normalise whitespace, strip code fences, then try json.loads.
    On failure, locate the first `{` ... matching `}` substring and try
    again on that. Returns None if no valid JSON object is present.

    For lists (e.g. `[{...}, {...}]`), use extract_json_value() instead.
    """
    text = coerce_message_text(raw).strip()
    if not text:
        return None

    # Strip ``` or ```json fences
    if text.startswith("```"):
        # Skip the opening fence + any language tag on the same line
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        # Strip the closing fence
        if "```" in text:
            text = text.rsplit("```", 1)[0]
        text = text.strip()

    # Normalise common Unicode artifacts
    for find, repl in _JSON_NORMALISE:
        text = text.replace(find, repl)

    # First try: parse as-is
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass

    # Second try: find the first { ... } balanced substring and parse it
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    result = json.loads(candidate)
                    return result if isinstance(result, dict) else None
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


def extract_json_array(raw: Any) -> Optional[list]:
    """Best-effort JSON-array extractor mirroring extract_json_object."""
    text = coerce_message_text(raw).strip()
    if not text:
        return None

    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
        text = text.strip()

    for find, repl in _JSON_NORMALISE:
        text = text.replace(find, repl)

    try:
        result = json.loads(text)
        return result if isinstance(result, list) else None
    except (json.JSONDecodeError, ValueError):
        pass

    # Match outermost [ ... ] ignoring strings
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return None
    try:
        result = json.loads(match.group(0))
        return result if isinstance(result, list) else None
    except (json.JSONDecodeError, ValueError):
        return None


def coerce_message_text(content: Any) -> str:
    """Flatten a LangChain message `content` field into a plain string.

    Newer ChatOpenAI / Anthropic returns can carry `content` as a list of
    blocks (e.g. `[{"type": "text", "text": "..."}]` or
    `[{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "..."}]`).
    Downstream callers in this repo expect a string for slicing, JSON
    parsing, regex matching, and length-based cost accounting — so we
    join the text blocks here and drop everything else.

    A previous bug: skill_registry called `result.get("summary", "")[:200]`,
    which raised `KeyError: slice(...)` because the LLM returned a dict-
    shaped content list. Routing every chat response through this helper
    prevents that class of failure.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    chunks.append(block["text"])
                elif "content" in block and isinstance(block["content"], str):
                    chunks.append(block["content"])
        return "".join(chunks)
    if content is None:
        return ""
    return str(content)
