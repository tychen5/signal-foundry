"""
Task 3 Router: SEC 10-K Extraction API.

Endpoints for extracting structured item-level data from SEC 10-K filings.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.logger import get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, ModelSelectionRequest, TaskType

router = APIRouter()
logger = get_logger("task3_router")


class SECExtractionRequest(BaseModel):
    """Request to extract structured data from a 10-K filing."""

    cik: Optional[str] = Field(default=None, description="Company CIK number (10-digit padded)")
    accession_number: Optional[str] = Field(default=None, description="Filing accession number")
    filing_url: Optional[str] = Field(default=None, description="Direct URL to 10-K filing")
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


class ItemExtraction(BaseModel):
    """A single extracted item from a 10-K filing."""

    part: str = Field(..., description="Part number (I, II, III, IV)")
    item_number: str = Field(..., description="Item number (1, 1A, 2, etc.)")
    item_title: str = Field(..., description="Item title")
    content_text: str = Field(..., description="Extracted text content")
    char_range: list[int] = Field(..., description="[start, end] character positions in source")
    status: str = Field(
        ...,
        description="extracted | incorporated_by_reference | not_applicable | reserved",
    )
    confidence: float = Field(default=0.0, description="Extraction confidence 0-1")
    extraction_method: str = Field(default="rule_based", description="Method used: rule_based | llm_refined | hybrid")


class SECExtractionResponse(BaseModel):
    """Complete extraction result for a 10-K filing."""

    filing_metadata: dict
    items: list[ItemExtraction]
    processing_metadata: dict


@router.post("/extract", response_model=ExecutionResult)
async def extract_10k(request: SECExtractionRequest):
    """
    Extract structured item-level data from a SEC 10-K filing.

    Pipeline: fetch → normalize → rule-based split → LLM refine → validate → XBRL cross-check

    Input: CIK + accession number, OR direct filing URL
    Output: Structured JSON with all 16 items, including status and char_range
    """
    from src.shared.logger import generate_trace_id

    trace_id = generate_trace_id()

    # Validate input
    if not request.cik and not request.filing_url:
        raise HTTPException(
            status_code=400,
            detail="Provide either (cik + accession_number) or filing_url",
        )

    logger.info(
        "sec_extraction_requested",
        cik=request.cik,
        accession=request.accession_number,
        url=request.filing_url,
        trace_id=trace_id,
    )

    # Pipeline implementation will be connected here
    return ExecutionResult(
        status=ExecutionStatus.SUCCESS,
        task=TaskType.SEC_EXTRACTION,
        trace_id=trace_id,
        result={
            "cik": request.cik,
            "accession_number": request.accession_number,
            "filing_url": request.filing_url,
            "message": "SEC extraction completed successfully (skeleton mode)",
            "items_extracted": 0,
        },
    )


@router.get("/filings/{cik}")
async def list_filings(cik: str, filing_type: str = "10-K", limit: int = 5):
    """
    List recent filings for a company by CIK.

    Useful for finding accession numbers to pass to /extract.
    """
    logger.info("listing_filings", cik=cik, filing_type=filing_type)

    # Will be connected to SEC EDGAR API
    return {
        "cik": cik,
        "filing_type": filing_type,
        "filings": [],
        "message": "Filing listing (skeleton mode)",
    }
