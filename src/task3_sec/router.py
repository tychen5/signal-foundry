"""
Task 3 Router: SEC 10-K Extraction API.

Full production endpoints for extracting structured item-level data from SEC 10-K filings.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.logger import generate_trace_id, get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, ModelSelectionRequest, TaskType

router = APIRouter()
logger = get_logger("task3_router")


class SECExtractionRequest(BaseModel):
    """Request to extract structured data from a 10-K filing."""

    cik: Optional[str] = Field(default=None, description="Company CIK number (any format)")
    accession_number: Optional[str] = Field(default=None, description="Filing accession number")
    filing_url: Optional[str] = Field(default=None, description="Direct URL to 10-K filing")
    skip_llm: bool = Field(default=False, description="Skip LLM refinement (rule-only mode)")
    skip_xbrl: bool = Field(default=False, description="Skip XBRL cross-validation")
    force_llm: bool = Field(
        default=False,
        description=(
            "Force Stage 2 LLM refinement on the lowest-confidence boundaries. "
            "Useful for reviewer benchmarks that compare text-only vs vision-assisted parsing."
        ),
    )
    use_vision: bool = Field(
        default=False,
        description=(
            "If true AND model is vision-capable, the LLM boundary refiner "
            "additionally receives a rendered PNG of the local context (±500 "
            "chars rendered as HTML) when uncertainty is high. Helpful on "
            "table-heavy / chart-heavy filings where text-only extraction "
            "drops layout cues. No-op for text-only NVIDIA models."
        ),
    )
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


@router.post("/extract", response_model=ExecutionResult)
async def extract_10k(request: SECExtractionRequest):
    """
    Extract structured item-level data from a SEC 10-K filing.

    Pipeline: fetch → normalize → rule-based split → LLM refine → validate → XBRL cross-check

    Input: CIK + accession number, OR direct filing URL
    Output: Structured JSON with all items, including status and char_range
    """
    trace_id = generate_trace_id()

    # Validate input
    if not request.cik and not request.filing_url:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'cik' (with optional 'accession_number') or 'filing_url'",
        )

    logger.info(
        "sec_extraction_requested",
        cik=request.cik,
        accession=request.accession_number,
        url=request.filing_url,
        skip_llm=request.skip_llm,
        trace_id=trace_id,
    )

    try:
        from src.task3_sec.pipeline import extract_10k as run_pipeline

        result = await run_pipeline(
            cik=request.cik,
            accession_number=request.accession_number,
            filing_url=request.filing_url,
            model_name=request.model.model_id,
            user_api_key=request.model.user_openrouter_key,
            skip_llm=request.skip_llm,
            skip_xbrl=request.skip_xbrl,
            use_vision=request.use_vision,
            force_llm=request.force_llm,
            trace_id=trace_id,
        )

        from src.shared.tracing import trace_url

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            task=TaskType.SEC_EXTRACTION,
            trace_id=trace_id,
            langsmith_trace_url=trace_url(trace_id),
            result=result.model_dump(),
            cost_metadata={
                "total_cost_usd": result.processing_metadata.total_cost_usd,
                "llm_calls": result.processing_metadata.llm_calls,
                "stages_used": result.processing_metadata.stages_used,
                "total_latency_ms": result.processing_metadata.total_latency_ms,
                "validation_overall_valid": result.processing_metadata.validation_report.get("overall_valid"),
                "xbrl_status": result.processing_metadata.xbrl_report.get("status"),
            },
            latency_ms=result.processing_metadata.total_latency_ms,
        )

    except ValueError as e:
        logger.warning("extraction_validation_error", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error("extraction_failed", error=str(e), trace_id=trace_id)
        from src.shared.llm_errors import classify_llm_error
        info = classify_llm_error(e)
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.SEC_EXTRACTION,
            trace_id=trace_id,
            error=str(e),
            failure_type=FailureType.PARSING_ERROR,
            cost_metadata={
                "error_category": info.category,
                "user_message": info.user_message,
                "suggested_action": info.suggested_action,
                "retryable": info.retryable,
            },
        )


@router.get("/filings/{cik}")
async def list_filings(cik: str, filing_type: str = "10-K", limit: int = 10):
    """
    List recent filings for a company by CIK.

    Useful for finding accession numbers to pass to /extract.
    """
    try:
        from src.task3_sec.fetcher import fetch_company_metadata

        metadata = await fetch_company_metadata(cik)

        # Filter by form type
        filings = [
            f
            for f in metadata.get("filings", [])
            if f.get("form", "") == filing_type or (filing_type == "10-K" and f.get("form", "") == "10-K/A")
        ][:limit]

        return {
            "cik": metadata.get("cik", cik),
            "company_name": metadata.get("company_name", ""),
            "tickers": metadata.get("tickers", []),
            "filing_type": filing_type,
            "count": len(filings),
            "filings": filings,
        }

    except Exception as e:
        logger.error("filing_list_failed", error=str(e), cik=cik)
        raise HTTPException(status_code=500, detail=f"Failed to list filings: {str(e)}")


@router.get("/company/{cik}")
async def company_info(cik: str):
    """Get company metadata from SEC EDGAR."""
    try:
        from src.task3_sec.fetcher import fetch_company_metadata

        metadata = await fetch_company_metadata(cik)
        return {
            "cik": metadata.get("cik", cik),
            "company_name": metadata.get("company_name", ""),
            "entity_type": metadata.get("entity_type", ""),
            "sic": metadata.get("sic", ""),
            "tickers": metadata.get("tickers", []),
            "exchanges": metadata.get("exchanges", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
