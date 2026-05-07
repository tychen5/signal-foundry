"""
Multi-modal vision support for Task 3 (optional).

For SEC filings the rule-based parser handles 95%+ of modern HTML cases
in microseconds at $0 cost. The remaining 5% are where text-only LLM
struggles too: tables embedded as image SVGs, complex multi-column
layouts, scanned older filings, or filings where item boundaries are
laid out visually rather than textually.

When `use_vision=True` AND the model is vision-capable AND we're in the
LLM refinement path (i.e. rule-based confidence was low), we render the
boundary's local context (a small HTML page wrapping the ±500-char text)
to a JPEG via headless playwright and send it alongside the text. The
LLM then has both the textual snippet AND the visual layout — useful
when boundaries are signaled by typography (bold heading, indentation,
ALL-CAPS lines) more than by literal "Item N." prose.

Cost guard: vision-rendering is async + opens a browser; we cap to 5
boundary refinements per filing to avoid runaway latency. Reviewers
can override via env `T3_VISION_MAX=N`.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Optional

from src.shared.logger import get_logger

logger = get_logger("task3_vision")


def _vision_max_renders() -> int:
    try:
        return int(os.environ.get("T3_VISION_MAX", "5"))
    except (TypeError, ValueError):
        return 5


async def render_text_to_jpeg_b64(
    text: str,
    width_px: int = 1024,
    quality: int = 75,
    timeout_ms: int = 8000,
) -> Optional[str]:
    """Render a text snippet to a styled HTML page → JPEG → base64.

    Strategy: wrap the text in a minimal HTML template that mimics SEC
    10-K typography (Times New Roman, item-heading bold), launch headless
    playwright, screenshot the rendered viewport, downsample to JPEG
    q=75. Returns None if playwright isn't available or render fails —
    callers must handle the no-vision case.
    """
    safe_text = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: 'Times New Roman', Times, serif; padding: 24px; color: #111; background: #fff; line-height: 1.4; max-width: {width_px}px; font-size: 14px; }}
  /* Mimic 10-K item-heading typography so bold pre/post-context is preserved */
  pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: inherit; font-size: 14px; }}
</style></head><body><pre>{safe_text}</pre></body></html>"""

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": width_px, "height": 768},
                device_scale_factor=1.0,
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="domcontentloaded", timeout=timeout_ms)
            png_bytes = await page.screenshot(full_page=True, type="png", timeout=timeout_ms)
            await browser.close()
    except Exception as e:
        logger.warning("t3_vision_render_failed", error=str(e)[:200])
        return None

    # Downsample PNG → JPEG q=75 to keep token cost reasonable.
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        # Cap height to keep tokens bounded — beyond first ~1500px is rarely useful
        if img.height > 1500:
            img = img.crop((0, 0, img.width, 1500))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpg_bytes = buf.getvalue()
    except Exception:
        # PIL not present — send the raw PNG anyway, just heavier
        jpg_bytes = png_bytes

    return base64.b64encode(jpg_bytes).decode("ascii")
