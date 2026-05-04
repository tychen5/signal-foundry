"""
XBRL Client for SEC 10-K Cross-Validation (Stage 4).

Fetches XBRL Company Facts from SEC API to cross-validate
extracted financial data. Useful for verifying Item 8 (Financial Statements).
"""

from __future__ import annotations

from typing import Any, Optional

from src.shared.logger import get_logger
from src.task3_sec.fetcher import fetch_xbrl_company_facts, normalize_cik

logger = get_logger("xbrl_client")


async def get_key_financial_facts(cik: str, fiscal_year: Optional[int] = None) -> dict:
    """
    Fetch key financial facts for cross-validation.

    Extracts common metrics like Revenue, Net Income, Total Assets
    from the XBRL Company Facts API.

    Args:
        cik: Company CIK
        fiscal_year: Target fiscal year (optional)

    Returns:
        Dict with key financial metrics, or empty dict on failure
    """
    data = await fetch_xbrl_company_facts(cik)
    if not data:
        return {}

    facts = data.get("facts", {})
    us_gaap = facts.get("us-gaap", {})

    key_metrics = {}

    # Extract common financial metrics
    metric_mappings = {
        "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
        "net_income": ["NetIncomeLoss", "ProfitLoss"],
        "total_assets": ["Assets"],
        "total_liabilities": ["Liabilities"],
        "stockholders_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "eps_basic": ["EarningsPerShareBasic"],
        "eps_diluted": ["EarningsPerShareDiluted"],
    }

    for metric_key, xbrl_tags in metric_mappings.items():
        for tag in xbrl_tags:
            if tag in us_gaap:
                values = _extract_values(us_gaap[tag], fiscal_year)
                if values:
                    key_metrics[metric_key] = values
                    break

    logger.info(
        "xbrl_facts_extracted",
        cik=normalize_cik(cik),
        metrics_found=list(key_metrics.keys()),
    )

    return key_metrics


def _extract_values(fact_data: dict, fiscal_year: Optional[int] = None) -> Optional[dict]:
    """Extract values from an XBRL fact entry."""
    units = fact_data.get("units", {})

    # Try USD first, then shares, then pure numbers
    for unit_key in ["USD", "USD/shares", "shares", "pure"]:
        if unit_key in units:
            entries = units[unit_key]

            if fiscal_year:
                # Filter to specific fiscal year
                year_entries = [
                    e for e in entries
                    if str(fiscal_year) in e.get("fy", str(fiscal_year))
                    or str(fiscal_year) in e.get("end", "")
                ]
                if year_entries:
                    latest = year_entries[-1]
                    return {
                        "value": latest.get("val"),
                        "unit": unit_key,
                        "period_end": latest.get("end", ""),
                        "form": latest.get("form", ""),
                    }
            else:
                # Get most recent 10-K value
                k_entries = [e for e in entries if e.get("form") == "10-K"]
                if k_entries:
                    latest = k_entries[-1]
                    return {
                        "value": latest.get("val"),
                        "unit": unit_key,
                        "period_end": latest.get("end", ""),
                        "form": latest.get("form", ""),
                    }

    return None


async def cross_validate_financials(
    cik: str,
    extracted_items: list,
    fiscal_year: Optional[int] = None,
) -> dict:
    """
    Cross-validate extracted financial data with XBRL facts.

    Args:
        cik: Company CIK
        extracted_items: List of ExtractedItem from pipeline
        fiscal_year: Target fiscal year

    Returns:
        Validation report with matches and discrepancies
    """
    xbrl_facts = await get_key_financial_facts(cik, fiscal_year)

    if not xbrl_facts:
        return {
            "status": "no_xbrl_data",
            "message": "XBRL data not available for cross-validation",
            "checks": [],
        }

    report = {
        "status": "completed",
        "xbrl_metrics_available": list(xbrl_facts.keys()),
        "checks": [],
    }

    # Check if key numbers appear in extracted Item 8 content
    item_8 = None
    for item in extracted_items:
        if hasattr(item, "item_number") and item.item_number == "8":
            item_8 = item
            break

    if item_8 and item_8.content_text:
        for metric_name, metric_data in xbrl_facts.items():
            if metric_data and "value" in metric_data:
                value = metric_data["value"]
                # Check if value (or formatted version) appears in content
                found = _check_value_in_text(value, item_8.content_text)
                report["checks"].append({
                    "metric": metric_name,
                    "xbrl_value": value,
                    "found_in_text": found,
                    "period": metric_data.get("period_end", ""),
                })

    logger.info(
        "xbrl_crossval_complete",
        cik=normalize_cik(cik),
        checks=len(report["checks"]),
    )

    return report


def _check_value_in_text(value: Any, text: str) -> bool:
    """Check if a financial value appears in the text (with formatting variations)."""
    if value is None:
        return False

    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value) in text

    # Try different formats
    formats_to_check = [
        str(int(num)),  # 12345678
        f"{num:,.0f}",  # 12,345,678
        f"{num / 1_000_000:,.0f}",  # Millions: 12
        f"{num / 1_000:,.0f}",  # Thousands: 12,346
    ]

    for fmt in formats_to_check:
        if fmt in text:
            return True

    return False
