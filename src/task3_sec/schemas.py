"""
SEC 10-K Extraction Schemas.

Pydantic models for the 10-K item-level structured extraction pipeline.
All 16 standard items across Parts I–IV are defined here.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ItemStatus(str, Enum):
    """Status of an extracted 10-K item."""

    EXTRACTED = "extracted"
    INCORPORATED_BY_REFERENCE = "incorporated_by_reference"
    NOT_APPLICABLE = "not_applicable"
    RESERVED = "reserved"
    NOT_FOUND = "not_found"


class ExtractionMethod(str, Enum):
    """How the item was extracted."""

    RULE_BASED = "rule_based"
    LLM_REFINED = "llm_refined"
    HYBRID = "hybrid"


# Standard 10-K item definitions (SEC regulation S-K)
STANDARD_10K_ITEMS: list[dict[str, str]] = [
    {"part": "I", "item_number": "1", "item_title": "Business"},
    {"part": "I", "item_number": "1A", "item_title": "Risk Factors"},
    {"part": "I", "item_number": "1B", "item_title": "Unresolved Staff Comments"},
    {"part": "I", "item_number": "1C", "item_title": "Cybersecurity"},
    {"part": "I", "item_number": "2", "item_title": "Properties"},
    {"part": "I", "item_number": "3", "item_title": "Legal Proceedings"},
    {"part": "I", "item_number": "4", "item_title": "Mine Safety Disclosures"},
    {"part": "II", "item_number": "5", "item_title": "Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities"},
    {"part": "II", "item_number": "6", "item_title": "Selected Financial Data"},
    {"part": "II", "item_number": "7", "item_title": "Management's Discussion and Analysis of Financial Condition and Results of Operations"},
    {"part": "II", "item_number": "7A", "item_title": "Quantitative and Qualitative Disclosures About Market Risk"},
    {"part": "II", "item_number": "8", "item_title": "Financial Statements and Supplementary Data"},
    {"part": "II", "item_number": "9", "item_title": "Changes in and Disagreements With Accountants on Accounting and Financial Disclosure"},
    {"part": "II", "item_number": "9A", "item_title": "Controls and Procedures"},
    {"part": "II", "item_number": "9B", "item_title": "Other Information"},
    {"part": "II", "item_number": "9C", "item_title": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections"},
    {"part": "III", "item_number": "10", "item_title": "Directors, Executive Officers and Corporate Governance"},
    {"part": "III", "item_number": "11", "item_title": "Executive Compensation"},
    {"part": "III", "item_number": "12", "item_title": "Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters"},
    {"part": "III", "item_number": "13", "item_title": "Certain Relationships and Related Transactions, and Director Independence"},
    {"part": "III", "item_number": "14", "item_title": "Principal Accountant Fees and Services"},
    {"part": "IV", "item_number": "15", "item_title": "Exhibits and Financial Statement Schedules"},
    {"part": "IV", "item_number": "16", "item_title": "Form 10-K Summary"},
]

# Short title variants for fuzzy matching
ITEM_TITLE_VARIANTS: dict[str, list[str]] = {
    "1": ["business"],
    "1A": ["risk factors"],
    "1B": ["unresolved staff comments"],
    "1C": ["cybersecurity"],
    "2": ["properties"],
    "3": ["legal proceedings"],
    "4": ["mine safety disclosures", "mine safety"],
    "5": ["market for", "common equity", "stockholder matters", "issuer purchases"],
    "6": ["selected financial data", "[reserved]", "reserved"],
    "7": ["management's discussion", "md&a", "management discussion"],
    "7A": ["quantitative and qualitative", "market risk"],
    "8": ["financial statements", "supplementary data"],
    "9": ["changes in and disagreements", "disagreements with accountants"],
    "9A": ["controls and procedures"],
    "9B": ["other information"],
    "9C": ["disclosure regarding foreign", "foreign jurisdictions"],
    "10": ["directors", "executive officers", "corporate governance"],
    "11": ["executive compensation"],
    "12": ["security ownership", "beneficial owners"],
    "13": ["certain relationships", "related transactions", "director independence"],
    "14": ["principal accountant", "accountant fees"],
    "15": ["exhibits", "financial statement schedules"],
    "16": ["form 10-k summary", "10-k summary"],
}


class FilingMetadata(BaseModel):
    """Metadata about the SEC filing."""

    cik: str = Field(..., description="Company CIK number")
    company_name: str = Field(default="", description="Company name")
    accession_number: str = Field(default="", description="Filing accession number")
    filing_date: str = Field(default="", description="Filing date (YYYY-MM-DD)")
    fiscal_year_end: str = Field(default="", description="Fiscal year end date")
    filing_url: str = Field(default="", description="URL to the filing document")
    form_type: str = Field(default="10-K", description="SEC form type")


class ExtractedItem(BaseModel):
    """A single extracted item from a 10-K filing."""

    part: str = Field(..., description="Part number (I, II, III, IV)")
    item_number: str = Field(..., description="Item number (1, 1A, 2, etc.)")
    item_title: str = Field(..., description="Item title")
    content_text: str = Field(default="", description="Extracted text content")
    char_range: list[int] = Field(
        default_factory=lambda: [0, 0],
        description="[start, end] character positions in source text",
    )
    status: ItemStatus = Field(default=ItemStatus.EXTRACTED, description="Extraction status")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Extraction confidence 0-1")
    extraction_method: ExtractionMethod = Field(
        default=ExtractionMethod.RULE_BASED, description="Method used"
    )
    reference_document: Optional[str] = Field(
        default=None, description="Referenced document (e.g., DEF 14A) for incorporated items"
    )
    reference_url: Optional[str] = Field(
        default=None, description="URL to referenced document"
    )


class ProcessingMetadata(BaseModel):
    """Metadata about the extraction process — cost/latency/method breakdown."""

    total_tokens_in: int = Field(default=0)
    total_tokens_out: int = Field(default=0)
    llm_calls: int = Field(default=0)
    rule_only_items: int = Field(default=0)
    llm_refined_items: int = Field(default=0)
    total_cost_usd: float = Field(default=0.0)
    total_latency_ms: float = Field(default=0.0)
    stages_used: list[str] = Field(default_factory=list)
    filing_char_count: int = Field(default=0)
    format_detected: str = Field(default="html", description="html | text | xbrl")
    validation_report: dict = Field(default_factory=dict)
    xbrl_report: dict = Field(default_factory=dict)
    # Honesty fields — exposed so callers can detect "we returned 22 items
    # but actually extracted zero" failure-masking. Added 2026-05-15 after
    # the Citi-2026 review surfaced that validation_report.overall_valid
    # alone could not distinguish "fully extracted" from "all placeholders".
    extracted_count: int = Field(
        default=0,
        description="Number of items with status != not_found (real extractions)",
    )
    expected_count: int = Field(
        default=0,
        description="Number of standard items the schema enumerates",
    )
    extraction_completeness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="extracted_count / expected_count — 0.0 means total failure",
    )


class ExtractionResult(BaseModel):
    """Complete extraction result for a 10-K filing."""

    filing_metadata: FilingMetadata
    items: list[ExtractedItem]
    processing_metadata: ProcessingMetadata
