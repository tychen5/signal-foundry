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
import os
from collections.abc import Mapping, Sequence
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


def vision_history_max() -> int:
    """Return the configurable max screenshot history depth.

    Controls how many labelled screenshots are kept in the rolling buffer
    and passed to the LLM. More screenshots = richer temporal context but
    higher token cost. Default 3 is a good balance.
    """
    try:
        return int(os.environ.get("T2_VISION_HISTORY_MAX", "3"))
    except (TypeError, ValueError):
        return 3


async def capture_full_page_screenshot_b64(
    page: Page,
    max_width_px: int = 1024,
    quality: int = 65,
    max_height_px: int = 2048,
) -> Optional[str]:
    """Capture the full page (including below-fold) as base64-encoded JPEG.

    Useful when the agent suspects relevant content is below the viewport
    (e.g., long tables, search results page 1 vs 2, footer contact info).
    Height is capped at max_height_px to avoid huge token payloads.
    Returns None on failure.
    """
    try:
        png_bytes = await page.screenshot(
            full_page=True,
            type="png",
            timeout=10000,
        )
    except Exception:
        return None

    try:
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if img.width > max_width_px:
            ratio = max_width_px / img.width
            img = img.resize(
                (max_width_px, int(img.height * ratio)),
                Image.LANCZOS,
            )
        if img.height > max_height_px:
            img = img.crop((0, 0, img.width, max_height_px))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpg_bytes = buf.getvalue()
    except Exception:
        jpg_bytes = png_bytes

    return base64.b64encode(jpg_bytes).decode("ascii")


async def capture_element_screenshot_b64(
    page: Page,
    selector: str,
    max_width_px: int = 1024,
    quality: int = 72,
) -> Optional[str]:
    """Capture a specific element as base64-encoded JPEG.

    Useful for focused vision on a chart, table, or specific widget where
    the full viewport includes too much irrelevant content. Selector can be
    CSS or ARIA role-based. Returns None on failure (element not found,
    not visible, etc).
    """
    try:
        element = page.locator(selector).first
        png_bytes = await element.screenshot(type="png", timeout=5000)
    except Exception:
        return None

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
        jpg_bytes = png_bytes

    return base64.b64encode(jpg_bytes).decode("ascii")


def annotate_screenshot_with_markers(
    screenshot_b64: str,
    markers: Sequence[Mapping[str, object]],
    quality: int = 72,
) -> Optional[str]:
    """Draw numbered bounding boxes on a screenshot for LLM grounding.

    Markers use pixel coordinates: {"x": 10, "y": 20, "width": 120,
    "height": 40, "label": "Search button"}. Returns a JPEG base64
    string, or None when the input is invalid. This helper is intentionally
    provider-agnostic so browser evals can add visual callouts without
    changing planner prompts.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        raw = base64.b64decode(screenshot_b64)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()

        for idx, marker in enumerate(markers, start=1):
            x = int(float(marker.get("x", 0)))
            y = int(float(marker.get("y", 0)))
            w = int(float(marker.get("width", 0)))
            h = int(float(marker.get("height", 0)))
            if w <= 0 or h <= 0:
                continue
            color = "#2563eb"
            draw.rectangle((x, y, x + w, y + h), outline=color, width=3)
            tag = str(idx)
            label = str(marker.get("label", "")).strip()
            if label:
                tag = f"{idx}: {label[:24]}"
            bbox = draw.textbbox((x, y), tag, font=font)
            draw.rectangle((bbox[0] - 3, bbox[1] - 2, bbox[2] + 3, bbox[3] + 2), fill=color)
            draw.text((x, y), tag, fill="#ffffff", font=font)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


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
