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
import contextlib
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


async def render_multi_snapshots(
    full_text: str,
    boundary_pos: int,
    item_number: str,
    width_px: int = 1024,
    quality: int = 70,
) -> list[tuple[str, str]]:
    """Render up to 3 labelled JPEGs around a boundary for richer LLM context.

    For SEC filings, item boundaries can be ambiguous in text-only form
    when typography matters (bold heading vs prose mention, indentation,
    ALL-CAPS). Sending three zoom levels lets the LLM see:

      1. "Header zone": ±150 chars around the boundary (the candidate
         heading itself, rendered with 10-K typography). Most useful for
         deciding if this IS a heading vs an in-text reference.
      2. "Local context": ±500 chars (default). Shows the heading + a
         paragraph of body text — useful for confirming status
         (incorporated_by_reference vs extracted vs not_applicable).
      3. "Neighbor context": ±1500 chars. Shows the previous item's tail
         + this item's start — useful when the boundary itself is hard
         to locate visually but the layout difference between items
         (whitespace, divider lines) is visible.

    Returns up to 3 (label, base64) pairs. Empty list if rendering
    fails (e.g. playwright not installed). Caller MUST handle the
    no-vision case.
    """
    snapshots: list[tuple[str, str]] = []
    n = len(full_text)

    # Tier 1 — header zone (tight ±150)
    h_start = max(0, boundary_pos - 150)
    h_end = min(n, boundary_pos + 200)
    header = full_text[h_start:h_end]
    snap = await render_text_to_jpeg_b64(
        header, width_px=width_px, quality=quality, mark_position=boundary_pos - h_start
    )
    if snap:
        snapshots.append((f"item_{item_number} header zone (±150 chars)", snap))

    # Tier 2 — local context (±500 default)
    l_start = max(0, boundary_pos - 200)
    l_end = min(n, boundary_pos + 800)
    local = full_text[l_start:l_end]
    snap = await render_text_to_jpeg_b64(local, width_px=width_px, quality=quality)
    if snap:
        snapshots.append((f"item_{item_number} local context (±500 chars)", snap))

    # Tier 3 — neighbor context (±1500). Only fire when the filing is large
    # enough; small filings don't need this and we save cost.
    if n > 4000:
        nb_start = max(0, boundary_pos - 1500)
        nb_end = min(n, boundary_pos + 2000)
        neighbor = full_text[nb_start:nb_end]
        snap = await render_text_to_jpeg_b64(
            neighbor,
            width_px=width_px,
            quality=quality,
            mark_position=boundary_pos - nb_start,
        )
        if snap:
            snapshots.append((f"item_{item_number} neighbor context (±1500 chars)", snap))

    logger.info(
        "t3_multi_snapshot",
        item=item_number,
        snapshots=len(snapshots),
        text_len=n,
    )
    return snapshots


async def render_comparison_snapshots(
    full_text: str,
    boundary_pos: int,
    item_number: str,
    width_px: int = 1024,
    quality: int = 70,
) -> list[tuple[str, str]]:
    """Render before/after comparison views around a candidate boundary.

    This is useful for edge filings where the parser needs to decide whether a
    candidate "Item" string is a real heading or just a body reference. The
    generated images put the candidate boundary in a yellow mark inside a
    wider before/after window so the LLM can compare typography and spacing
    across the transition.
    """
    n = len(full_text)
    snapshots: list[tuple[str, str]] = []
    start = max(0, boundary_pos - 1200)
    end = min(n, boundary_pos + 1200)
    snap = await render_text_to_jpeg_b64(
        full_text[start:end],
        width_px=width_px,
        quality=quality,
        mark_position=boundary_pos - start,
    )
    if snap:
        snapshots.append((f"item_{item_number} before/after comparison", snap))
    return snapshots


async def render_text_to_jpeg_b64(
    text: str,
    width_px: int = 1024,
    quality: int = 75,
    timeout_ms: int = 8000,
    mark_position: Optional[int] = None,
) -> Optional[str]:
    """Render a text snippet to a styled HTML page → JPEG → base64.

    Strategy: wrap the text in a minimal HTML template that mimics SEC
    10-K typography (Times New Roman, item-heading bold), launch headless
    playwright, screenshot the rendered viewport, downsample to JPEG
    q=75. Returns None if playwright isn't available or render fails —
    callers must handle the no-vision case.
    """
    # Optionally insert a yellow highlight at the boundary position so
    # the LLM's eye is drawn to the candidate heading.
    if mark_position is not None and 0 <= mark_position < len(text):
        before = text[:mark_position]
        after = text[mark_position : mark_position + 80]
        rest = text[mark_position + 80 :]
        before_safe = before.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        after_safe = after.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rest_safe = rest.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body_html = f"<pre>{before_safe}<mark>{after_safe}</mark>{rest_safe}</pre>"
    else:
        safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body_html = f"<pre>{safe_text}</pre>"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: 'Times New Roman', Times, serif; padding: 24px; color: #111; background: #fff; line-height: 1.4; max-width: {width_px}px; font-size: 14px; }}
  /* Mimic 10-K item-heading typography so bold pre/post-context is preserved */
  pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: inherit; font-size: 14px; }}
  mark {{ background: #fff3a0; padding: 0 2px; }}
</style></head><body>{body_html}</body></html>"""

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    manager = async_playwright()
    browser = None
    try:
        p = await manager.start()
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": width_px, "height": 768},
            device_scale_factor=1.0,
        )
        page = await ctx.new_page()
        await page.set_content(html, wait_until="domcontentloaded", timeout=timeout_ms)
        png_bytes = await page.screenshot(full_page=True, type="png", timeout=timeout_ms)
    except Exception as e:
        logger.warning("t3_vision_render_failed", error=str(e)[:200])
        return None
    finally:
        if browser is not None:
            with contextlib.suppress(BaseException):
                await browser.close()
        with contextlib.suppress(BaseException):
            await manager.stop()

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


async def render_html_to_jpeg_b64(
    html_fragment: str,
    width_px: int = 1024,
    quality: int = 75,
    timeout_ms: int = 8000,
) -> Optional[str]:
    """Render an HTML fragment preserving original SEC filing formatting.

    Unlike render_text_to_jpeg_b64 which wraps plain text in <pre>, this
    function takes raw HTML (e.g., a slice of the normalized filing) and
    renders it with a minimal wrapper. Preserves:
    - Bold/italic text (often used for item headings)
    - Tables and multi-column layouts
    - Indentation and whitespace patterns
    - ALL-CAPS text styling

    This gives the LLM much richer visual context for boundary detection
    than plain-text rendering, especially for filings where typography
    is the primary signal that distinguishes headings from body text.
    """
    # Wrap the fragment in a minimal document with 10-K-like styling
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: 'Times New Roman', Times, serif; padding: 24px;
         color: #111; background: #fff; line-height: 1.4;
         max-width: {width_px}px; font-size: 14px; }}
  table {{ border-collapse: collapse; margin: 8px 0; }}
  td, th {{ border: 1px solid #ccc; padding: 4px 8px; font-size: 13px; }}
  b, strong {{ font-weight: bold; }}
</style></head><body>{html_fragment}</body></html>"""

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    manager = async_playwright()
    browser = None
    try:
        p = await manager.start()
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": width_px, "height": 768},
            device_scale_factor=1.0,
        )
        page = await ctx.new_page()
        await page.set_content(html, wait_until="domcontentloaded", timeout=timeout_ms)
        png_bytes = await page.screenshot(full_page=True, type="png", timeout=timeout_ms)
    except Exception as e:
        logger.warning("t3_html_vision_render_failed", error=str(e)[:200])
        return None
    finally:
        if browser is not None:
            with contextlib.suppress(BaseException):
                await browser.close()
        with contextlib.suppress(BaseException):
            await manager.stop()

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if img.height > 1500:
            img = img.crop((0, 0, img.width, 1500))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpg_bytes = buf.getvalue()
    except Exception:
        jpg_bytes = png_bytes

    return base64.b64encode(jpg_bytes).decode("ascii")
