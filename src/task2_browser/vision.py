"""
Multi-modal vision support for Task 2 (optional).

Vision-language models (Gemini 3.1 Pro, Claude Opus 4.7, GPT-5.5) can
accept screenshots alongside the AOM tree text. Sending the rendered
viewport to the verifier / planner adds robustness for cases where the
accessibility tree is sparse or the visual layout encodes information
the AOM doesn't (charts, tabulated finance data, captcha challenges).

Design notes:
- Vision is OPT-IN. The default flow is AOM-only — cheaper, faster, and
  good enough for ~80% of cases. Reviewers/users explicitly toggle
  `use_vision=true` when they need the extra signal.
- Only activate for known vision-capable models. Sending image_url to a
  text-only model (kimi/glm/deepseek/minimax) raises a 4xx; we silently
  fall back to text-only context in that case.
- Screenshots are downsampled to 1024px wide, JPEG q=72, base64 — cuts
  payload from ~500 KB to ~70 KB while preserving readability.
"""

from __future__ import annotations

import base64
import io
from typing import Optional

from langchain_core.messages import HumanMessage
from playwright.async_api import Page

VISION_CAPABLE_MODELS: frozenset[str] = frozenset(
    {
        # OpenRouter — confirmed multi-modal
        "google/gemini-3.1-pro-preview",
        "anthropic/claude-opus-4.7",
        "openai/gpt-5.5",
    }
)

# NVIDIA NIM models in our registry that are TEXT-ONLY. Sending image_url
# to these returns a 400. We track the explicit list so the toggle still
# accepts use_vision=True and we can WARN rather than error.
TEXT_ONLY_MODELS: frozenset[str] = frozenset(
    {
        "moonshotai/kimi-k2.6",
        "z-ai/glm-5.1",
        "deepseek-ai/deepseek-v4-pro",
        "minimaxai/minimax-m2.7",
    }
)


def is_vision_capable(model_name: Optional[str]) -> bool:
    """Return True if the model accepts image_url content blocks.

    For text-only NVIDIA NIM models in our registry the answer is firmly
    No. Unknown models default to No (safest — the worst that happens
    is we miss a vision opportunity, instead of a 400).
    """
    if not model_name:
        return False
    return model_name in VISION_CAPABLE_MODELS


async def capture_screenshot_b64(
    page: Page,
    max_width_px: int = 1024,
    quality: int = 72,
) -> Optional[str]:
    """Capture viewport as base64-encoded JPEG. Returns None on failure.

    JPEG @ q=72 hits the cost-vs-fidelity sweet spot for LLM consumption:
    ~70 KB for 1024-wide vs ~500 KB for raw PNG, and the LLM can still
    read text/buttons reliably.
    """
    try:
        png_bytes = await page.screenshot(
            full_page=False,
            type="png",
            timeout=8000,
        )
    except Exception:
        return None

    # Downsample + recompress to JPEG to keep token cost bounded
    try:
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if img.width > max_width_px:
            ratio = max_width_px / img.width
            img = img.resize(
                (max_width_px, int(img.height * ratio)),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpg_bytes = buf.getvalue()
    except Exception:
        # PIL not available — send the raw PNG (heavier but still works)
        jpg_bytes = png_bytes
        return base64.b64encode(jpg_bytes).decode("ascii")

    return base64.b64encode(jpg_bytes).decode("ascii")


def make_multimodal_message(
    text: str,
    screenshot_b64: Optional[str],
    mime: str = "image/jpeg",
) -> HumanMessage:
    """Build a HumanMessage that mixes text + an inline image.

    Compatible with langchain_openai.ChatOpenAI for both OpenRouter and
    NVIDIA-NIM endpoints (both pass `image_url` content blocks through).
    For text-only or missing screenshot, returns a plain-text message.
    """
    if not screenshot_b64:
        return HumanMessage(content=text)

    return HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{screenshot_b64}"},
            },
            {"type": "text", "text": text},
        ]
    )


def make_multimodal_message_history(
    text: str,
    screenshots_b64: list[tuple[str, str]],
    mime: str = "image/jpeg",
) -> HumanMessage:
    """Build a HumanMessage with multiple labelled screenshots + text.

    Args:
        text: The user-prompt text (task description, AOM tree, etc.)
        screenshots_b64: list of (label, base64) pairs — newest LAST so
            the LLM sees the chronological progression. Labels like
            "before navigation", "after click", "current viewport".

    For Task 2 multi-step flows the LLM needs to see CHANGE over time
    (a button click that did nothing, a modal that just popped up, an
    error toast that appeared). One screenshot misses these dynamics;
    a labelled history puts them in front of the model.
    """
    if not screenshots_b64:
        return HumanMessage(content=text)

    parts: list[dict] = []
    for label, b64 in screenshots_b64:
        # Label as text BEFORE the image so the LLM knows what it's looking at
        parts.append({"type": "text", "text": f"[{label}]"})
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )
    parts.append({"type": "text", "text": text})
    return HumanMessage(content=parts)
