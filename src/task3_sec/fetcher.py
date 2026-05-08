"""
SEC EDGAR API Client (Fetcher).

Handles all interactions with SEC EDGAR APIs:
- Submissions API: company metadata + filing index
- Filing download: raw HTML/text content
- Rate limiting: 10 req/sec with asyncio throttle
- Caching: in-memory cache to avoid redundant fetches
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from src.config import get_settings
from src.shared.logger import get_logger

logger = get_logger("sec_fetcher")

# SEC API rate limit: 10 requests per second
_rate_limiter = asyncio.Semaphore(8)
_request_lock = asyncio.Lock()
_last_request_time: float = 0.0
_MIN_REQUEST_INTERVAL = 0.12  # ~8 req/sec to stay safely under 10
_MAX_RETRIES = 3
_MEMORY_CACHE_MAX_CHARS = 5_000_000

# In-memory cache for fetched content
_cache: dict[str, str] = {}
_metadata_cache: dict[str, dict] = {}


class SECDownloadError(RuntimeError):
    """Raised when a SEC filing cannot be downloaded safely."""


def _get_headers() -> dict[str, str]:
    """Get required headers for SEC API requests."""
    settings = get_settings()
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


async def _respect_rate_limit() -> None:
    """Apply a process-wide fair-access delay before each SEC request."""
    global _last_request_time

    async with _request_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()


async def _rate_limited_get(url: str, timeout: float = 60.0) -> httpx.Response:
    """Make a rate-limited GET request to SEC APIs with bounded retries."""
    async with _rate_limiter:
        async with httpx.AsyncClient(
            headers=_get_headers(),
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            for attempt in range(_MAX_RETRIES):
                await _respect_rate_limit()
                try:
                    response = await client.get(url)
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(0.75 * (2**attempt))
                        continue
                    response.raise_for_status()
                    return response
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if attempt >= _MAX_RETRIES - 1:
                        raise
                    logger.warning(
                        "sec_request_retry",
                        url=url[:100],
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    await asyncio.sleep(0.75 * (2**attempt))

    raise SECDownloadError(f"SEC request failed after {_MAX_RETRIES} attempts: {url}")


def _cache_path(url: str) -> Path:
    """Return the disk cache path for a SEC URL."""
    settings = get_settings()
    cache_dir = Path(settings.sec_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.txt"


def _read_disk_cache(url: str) -> Optional[str]:
    """Read cached filing text from disk if available."""
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        logger.info("cache_hit", source="disk_filing_content", url=url[:80])
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("disk_cache_read_failed", path=str(path), error=str(exc))
        return None


def _write_disk_cache(url: str, content: str) -> None:
    """Persist filing text to disk cache for repeat eval runs."""
    path = _cache_path(url)
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.warning("disk_cache_write_failed", path=str(path), error=str(exc))


async def _download_text_streaming(url: str, timeout: float) -> str:
    """Download a potentially large SEC filing while enforcing a byte ceiling."""
    settings = get_settings()
    max_bytes = settings.sec_max_download_mb * 1024 * 1024

    async with _rate_limiter:
        async with httpx.AsyncClient(
            headers=_get_headers(),
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            for attempt in range(_MAX_RETRIES):
                await _respect_rate_limit()
                try:
                    async with client.stream("GET", url) as response:
                        if response.status_code in {429, 500, 502, 503, 504} and attempt < _MAX_RETRIES - 1:
                            await response.aread()
                            await asyncio.sleep(0.75 * (2**attempt))
                            continue

                        response.raise_for_status()

                        content_length = response.headers.get("content-length")
                        if content_length and int(content_length) > max_bytes:
                            raise SECDownloadError(
                                f"SEC filing is {content_length} bytes, above configured limit of {max_bytes} bytes"
                            )

                        chunks = bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > max_bytes:
                                raise SECDownloadError(
                                    f"SEC filing exceeded configured limit of {max_bytes} bytes while downloading"
                                )

                        encoding = response.encoding or "utf-8"
                        return bytes(chunks).decode(encoding, errors="replace")
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if attempt >= _MAX_RETRIES - 1:
                        raise
                    logger.warning(
                        "sec_stream_retry",
                        url=url[:100],
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    await asyncio.sleep(0.75 * (2**attempt))

    raise SECDownloadError(f"SEC filing download failed after {_MAX_RETRIES} attempts: {url}")


def normalize_cik(cik: str) -> str:
    """Normalize CIK to 10-digit zero-padded format."""
    cik_clean = re.sub(r"\D", "", cik)
    return cik_clean.zfill(10)


def normalize_accession(accession: str) -> str:
    """Normalize accession number — keep dashes for display, strip for URLs.

    Real SEC accessions follow the form ``\\d{10}-\\d{2}-\\d{6}`` (with
    dashes) or 18 contiguous digits (no dashes). We normalise both into
    the canonical dashed form so downstream URL construction and the
    Submissions API filtering work the same way regardless of input
    style. Invalid shapes are returned unchanged — the validator
    elsewhere is responsible for surfacing a clear error.
    """
    s = accession.strip()
    # Already in canonical dashed form
    if re.fullmatch(r"\d{10}-\d{2}-\d{6}", s):
        return s
    # 18-digit no-dash form — restore dashes
    if re.fullmatch(r"\d{18}", s):
        return f"{s[:10]}-{s[10:12]}-{s[12:]}"
    return s


def is_valid_accession_shape(accession: str) -> bool:
    """Cheap shape check for SEC accession numbers.

    Returns True only for the two valid forms: 18 digits with two
    dashes (``0000320193-23-000106``) or 18 contiguous digits. Anything
    else (typos, partial copy, X-or-letter in the middle) is rejected.
    """
    s = accession.strip()
    return bool(re.fullmatch(r"\d{10}-\d{2}-\d{6}", s) or re.fullmatch(r"\d{18}", s))


def accession_no_dashes(accession: str) -> str:
    """Remove dashes from accession number for URL construction."""
    return accession.replace("-", "")


def parse_filing_url_metadata(filing_url: str) -> dict[str, str]:
    """
    Parse CIK/accession/primary document from a SEC Archives filing URL.

    Supports URLs like:
    https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm
    """
    match = re.search(
        r"/Archives/edgar/data/(?P<cik>\d+)/(?P<accession_nodash>\d+)/(?P<filename>[^/?#]+)",
        filing_url,
        flags=re.IGNORECASE,
    )
    if not match:
        return {}

    accession_nodash = match.group("accession_nodash")
    accession_number = ""
    filename = match.group("filename")
    file_acc_match = re.search(r"(\d{10}-\d{2}-\d{6})", filename)
    if file_acc_match:
        accession_number = file_acc_match.group(1)
    elif len(accession_nodash) == 18:
        accession_number = f"{accession_nodash[:10]}-{accession_nodash[10:12]}-{accession_nodash[12:]}"

    return {
        "cik": normalize_cik(match.group("cik")),
        "accession_number": accession_number,
        "primary_document": filename,
    }


async def fetch_company_metadata(cik: str) -> dict:
    """
    Fetch company metadata and filing list from SEC Submissions API.

    Args:
        cik: Company CIK number (any format, will be normalized)

    Returns:
        Dict with company info and recent filings
    """
    cik_padded = normalize_cik(cik)
    cache_key = f"metadata_{cik_padded}"

    if cache_key in _metadata_cache:
        logger.info("cache_hit", source="metadata", cik=cik_padded)
        return _metadata_cache[cache_key]

    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    logger.info("fetching_metadata", cik=cik_padded, url=url)

    response = await _rate_limited_get(url)
    data = response.json()

    result = {
        "cik": data.get("cik", cik_padded),
        "company_name": data.get("name", ""),
        "entity_type": data.get("entityType", ""),
        "sic": data.get("sic", ""),
        "tickers": data.get("tickers", []),
        "exchanges": data.get("exchanges", []),
        "filings": _parse_recent_filings(data),
        "filing_files": data.get("filings", {}).get("files", []),
    }

    _metadata_cache[cache_key] = result
    return result


def _parse_recent_filings(data: dict) -> list[dict]:
    """Parse recent filings from submissions API response."""
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    return _parse_filing_columns(recent)


def _parse_filing_columns(columns: dict) -> list[dict]:
    """Parse SEC columnar filing metadata into row dictionaries."""
    filings = []
    forms = columns.get("form", [])
    dates = columns.get("filingDate", [])
    accessions = columns.get("accessionNumber", [])
    primary_docs = columns.get("primaryDocument", [])
    descriptions = columns.get("primaryDocDescription", [])

    for i in range(len(forms)):
        filings.append({
            "form": forms[i] if i < len(forms) else "",
            "filing_date": dates[i] if i < len(dates) else "",
            "accession_number": accessions[i] if i < len(accessions) else "",
            "primary_document": primary_docs[i] if i < len(primary_docs) else "",
            "description": descriptions[i] if i < len(descriptions) else "",
        })

    return filings


async def fetch_company_filing_file(file_name: str) -> list[dict]:
    """
    Fetch an older submissions file referenced by the main Submissions API.

    The main `recent` array only includes the latest window. Older filings live
    in files such as `CIK0000320193-submissions-001.json`.
    """
    cache_key = f"submission_file_{file_name}"
    if cache_key in _metadata_cache:
        return _metadata_cache[cache_key]

    url = f"https://data.sec.gov/submissions/{file_name}"
    response = await _rate_limited_get(url, timeout=30.0)
    filings = _parse_filing_columns(response.json())
    _metadata_cache[cache_key] = filings
    return filings


async def find_10k_filing(
    cik: str,
    accession_number: Optional[str] = None,
    year: Optional[int] = None,
) -> dict:
    """
    Find a specific 10-K filing for a company.

    Args:
        cik: Company CIK
        accession_number: Specific accession number (if known)
        year: Filing year (finds most recent if not specified)

    Returns:
        Dict with filing metadata including download URL
    """
    metadata = await fetch_company_metadata(cik)
    cik_padded = normalize_cik(cik)
    cik_raw = cik_padded.lstrip("0") or "0"

    # Primary filter: 10-K family. But if a specific accession is provided
    # and isn't a 10-K, also try 20-F (foreign private issuer) and 10-KSB
    # (older small-business form) — the API consumer is asking for THIS
    # filing, not "the latest 10-K".
    filings_10k = [
        f for f in metadata["filings"]
        if f["form"] in ("10-K", "10-K/A", "20-F", "20-F/A", "10-KSB", "10-KSB/A")
    ]

    if not filings_10k:
        raise ValueError(f"No 10-K / 20-F filings found for CIK {cik}")

    # Find specific filing
    target = None
    if accession_number:
        acc_clean = accession_number.strip()
        for f in filings_10k:
            if f["accession_number"] == acc_clean:
                target = f
                break
        if not target:
            # Try without exact match — compare without dashes
            acc_nodash = acc_clean.replace("-", "")
            for f in filings_10k:
                if f["accession_number"].replace("-", "") == acc_nodash:
                    target = f
                    break

    if not target:
        if accession_number:
            target = await _find_in_additional_submission_files(
                filing_files=metadata.get("filing_files", []),
                accession_number=accession_number,
                year=None,
            )
        elif year:
            target = await _find_in_additional_submission_files(
                filing_files=metadata.get("filing_files", []),
                accession_number=None,
                year=year,
            )

    if accession_number and not target:
        archive_target = await resolve_filing_from_archive(cik, accession_number)
        if archive_target:
            archive_target["company_name"] = metadata["company_name"]
            return archive_target
        raise ValueError(f"10-K filing accession {accession_number} not found for CIK {cik}")

    if not target:
        if year:
            for f in filings_10k:
                if f["filing_date"].startswith(str(year)):
                    target = f
                    break
        if not target:
            target = filings_10k[0]  # Most recent

    # Build filing URL.
    # When primary_document is missing (common for older filings whose
    # additional-submissions records don't include it), probe the archive
    # directory listing to find the real primary document. If that also
    # fails (very old pre-1996 filings), fall back to {accession}.txt
    # which is the canonical SGML complete-submission name.
    acc_nodash = accession_no_dashes(target["accession_number"])
    primary_doc = target.get("primary_document", "")

    if not primary_doc:
        archive_resolved = await resolve_filing_from_archive(
            cik_padded, target["accession_number"]
        )
        if archive_resolved:
            return {
                **archive_resolved,
                "company_name": metadata["company_name"],
                "form_type": archive_resolved.get("form_type") or target.get("form", "10-K"),
            }
        # Last-resort: SGML complete-submission .txt (works for pre-1996)
        primary_doc = f"{target['accession_number']}.txt"

    filing_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/"
        f"{acc_nodash}/{primary_doc}"
    )

    return {
        "cik": cik_padded,
        "company_name": metadata["company_name"],
        "accession_number": target["accession_number"],
        "filing_date": target["filing_date"],
        "primary_document": primary_doc,
        "filing_url": filing_url,
        "form_type": target["form"],
    }


async def _find_in_additional_submission_files(
    filing_files: list[dict],
    accession_number: Optional[str],
    year: Optional[int],
) -> Optional[dict]:
    """Search older Submissions API files for a 10-K target."""
    for file_info in filing_files:
        file_name = file_info.get("name", "")
        if not file_name:
            continue
        if year:
            filing_from = file_info.get("filingFrom", "")
            filing_to = file_info.get("filingTo", "")
            if filing_from and filing_to and not (filing_from[:4] <= str(year) <= filing_to[:4]):
                continue

        filings = await fetch_company_filing_file(file_name)
        filings_10k = [f for f in filings if f["form"] in ("10-K", "10-K/A")]

        if accession_number:
            acc_clean = accession_number.strip()
            acc_nodash = acc_clean.replace("-", "")
            for filing in filings_10k:
                if filing["accession_number"] == acc_clean or filing["accession_number"].replace("-", "") == acc_nodash:
                    return filing
        elif year:
            for filing in filings_10k:
                if filing["filing_date"].startswith(str(year)):
                    return filing

    return None


async def resolve_filing_from_archive(cik: str, accession_number: str) -> Optional[dict]:
    """
    Resolve a filing directly from the SEC Archives accession directory.

    This is the final fallback for valid older accessions that are not present
    in the main `recent` submissions window.
    """
    cik_padded = normalize_cik(cik)
    cik_raw = cik_padded.lstrip("0") or "0"
    acc_clean = normalize_accession(accession_number)
    acc_nodash = accession_no_dashes(acc_clean)
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_nodash}/index.json"

    try:
        response = await _rate_limited_get(index_url, timeout=30.0)
        items = response.json().get("directory", {}).get("item", [])
    except Exception as exc:
        logger.warning("archive_index_fetch_failed", cik=cik_padded, accession=acc_clean, error=str(exc))
        items = []

    primary_doc = _choose_primary_document(items, acc_clean)
    if not primary_doc:
        txt_name = f"{acc_clean}.txt"
        primary_doc = txt_name

    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_nodash}/{primary_doc}"
    return {
        "cik": cik_padded,
        "company_name": "",
        "accession_number": acc_clean,
        "filing_date": "",
        "primary_document": primary_doc,
        "filing_url": filing_url,
        "form_type": "10-K",
    }


def _choose_primary_document(items: list[dict], accession_number: str) -> str:
    """Choose the most likely primary 10-K document from an Archives index."""
    names = [item.get("name", "") for item in items if item.get("name")]
    html_names = [
        name for name in names
        if name.lower().endswith((".htm", ".html"))
        and "index" not in name.lower()
        and not _looks_like_exhibit_name(name)
    ]
    if html_names:
        return html_names[0]

    accession_txt = f"{accession_number}.txt"
    if accession_txt in names:
        return accession_txt

    return ""


def _looks_like_exhibit_name(name: str) -> bool:
    """Return True if a document name likely points to an exhibit."""
    lowered = name.lower()
    return (
        lowered.startswith("ex")
        or "exhibit" in lowered
        or re.search(r"d\d+dex", lowered) is not None
        or lowered.endswith((".xml", ".xsd", ".jpg", ".jpeg", ".gif", ".png"))
    )


async def fetch_filing_content(filing_url: str) -> str:
    """
    Download the actual 10-K filing HTML/text content.

    Args:
        filing_url: Direct URL to the filing document

    Returns:
        Raw HTML or text content of the filing
    """
    if filing_url in _cache:
        logger.info("cache_hit", source="filing_content", url=filing_url[:80])
        return _cache[filing_url]

    disk_cached = _read_disk_cache(filing_url)
    if disk_cached is not None:
        if len(disk_cached) <= _MEMORY_CACHE_MAX_CHARS:
            _cache[filing_url] = disk_cached
        return disk_cached

    logger.info("fetching_filing", url=filing_url[:80])
    settings = get_settings()
    content = await _download_text_streaming(filing_url, timeout=settings.sec_request_timeout_sec)

    _write_disk_cache(filing_url, content)
    if len(content) <= _MEMORY_CACHE_MAX_CHARS:
        _cache[filing_url] = content
    logger.info("filing_fetched", chars=len(content), url=filing_url[:80])

    return content


async def find_proxy_statement(cik: str, year: int) -> Optional[dict]:
    """
    Find DEF 14A (Proxy Statement) for incorporated-by-reference resolution.

    Args:
        cik: Company CIK
        year: Filing year to search around

    Returns:
        Dict with proxy filing info, or None if not found
    """
    try:
        metadata = await fetch_company_metadata(cik)
        proxy_filings = [
            f for f in metadata["filings"]
            if f["form"] in ("DEF 14A", "DEFA14A")
            and (f["filing_date"].startswith(str(year)) or f["filing_date"].startswith(str(year + 1)))
        ]

        if proxy_filings:
            target = proxy_filings[0]
            cik_raw = normalize_cik(cik).lstrip("0") or "0"
            acc_nodash = accession_no_dashes(target["accession_number"])
            return {
                "accession_number": target["accession_number"],
                "filing_date": target["filing_date"],
                "url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/"
                    f"{acc_nodash}/{target.get('primary_document', '')}"
                ),
            }
    except Exception as e:
        logger.warning("proxy_search_failed", cik=cik, year=year, error=str(e))

    return None


async def fetch_xbrl_company_facts(cik: str) -> Optional[dict]:
    """
    Fetch XBRL Company Facts for cross-validation.

    Args:
        cik: Company CIK

    Returns:
        XBRL facts dict, or None on failure
    """
    cik_padded = normalize_cik(cik)
    cache_key = f"xbrl_{cik_padded}"

    if cache_key in _metadata_cache:
        return _metadata_cache[cache_key]

    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
        response = await _rate_limited_get(url, timeout=30.0)
        data = response.json()
        _metadata_cache[cache_key] = data
        return data
    except Exception as e:
        logger.warning("xbrl_fetch_failed", cik=cik_padded, error=str(e))
        return None


def clear_cache() -> None:
    """Clear all caches (useful for testing)."""
    _cache.clear()
    _metadata_cache.clear()
