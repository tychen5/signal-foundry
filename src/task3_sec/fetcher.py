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
import re
import time
from typing import Optional
from functools import lru_cache

import httpx

from src.config import get_settings
from src.shared.logger import get_logger

logger = get_logger("sec_fetcher")

# SEC API rate limit: 10 requests per second
_rate_limiter = asyncio.Semaphore(8)
_last_request_time: float = 0.0
_MIN_REQUEST_INTERVAL = 0.12  # ~8 req/sec to stay safely under 10

# In-memory cache for fetched content
_cache: dict[str, str] = {}
_metadata_cache: dict[str, dict] = {}


def _get_headers() -> dict[str, str]:
    """Get required headers for SEC API requests."""
    settings = get_settings()
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml,application/json",
    }


async def _rate_limited_get(url: str, timeout: float = 60.0) -> httpx.Response:
    """Make a rate-limited GET request to SEC APIs."""
    global _last_request_time

    async with _rate_limiter:
        # Enforce minimum interval between requests
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        _last_request_time = time.time()

        async with httpx.AsyncClient(
            headers=_get_headers(),
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response


def normalize_cik(cik: str) -> str:
    """Normalize CIK to 10-digit zero-padded format."""
    cik_clean = re.sub(r"\D", "", cik)
    return cik_clean.zfill(10)


def normalize_accession(accession: str) -> str:
    """Normalize accession number — keep dashes for display, strip for URLs."""
    return accession.strip()


def accession_no_dashes(accession: str) -> str:
    """Remove dashes from accession number for URL construction."""
    return accession.replace("-", "")


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
    }

    _metadata_cache[cache_key] = result
    return result


def _parse_recent_filings(data: dict) -> list[dict]:
    """Parse recent filings from submissions API response."""
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    filings = []
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    for i in range(len(forms)):
        filings.append({
            "form": forms[i] if i < len(forms) else "",
            "filing_date": dates[i] if i < len(dates) else "",
            "accession_number": accessions[i] if i < len(accessions) else "",
            "primary_document": primary_docs[i] if i < len(primary_docs) else "",
            "description": descriptions[i] if i < len(descriptions) else "",
        })

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

    filings_10k = [
        f for f in metadata["filings"]
        if f["form"] in ("10-K", "10-K/A")
    ]

    if not filings_10k:
        raise ValueError(f"No 10-K filings found for CIK {cik}")

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
        if year:
            for f in filings_10k:
                if f["filing_date"].startswith(str(year)):
                    target = f
                    break
        if not target:
            target = filings_10k[0]  # Most recent

    # Build filing URL
    acc_nodash = accession_no_dashes(target["accession_number"])
    primary_doc = target.get("primary_document", "")

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

    logger.info("fetching_filing", url=filing_url[:80])
    response = await _rate_limited_get(filing_url, timeout=120.0)
    content = response.text

    # Cache the content
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
