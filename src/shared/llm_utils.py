"""Cross-provider helpers for working with LangChain chat-model responses."""

from __future__ import annotations

from typing import Any


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
