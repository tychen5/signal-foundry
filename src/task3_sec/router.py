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
    max_cost_usd: Optional[float] = Field(
        default=None,
        description=(
            "Per-request budget cap (USD). When set, the pipeline halts "
            "further LLM-driven stages once cumulative spend on this trace "
            "exceeds the cap. Default: $0.50 per filing (matches the spec). "
            "Set to 0 to disable for benchmarks."
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

    # Cheap shape check on accession — catches typos before we burn an SEC
    # request and a clone roundtrip on a clearly invalid string.
    if request.accession_number:
        from src.task3_sec.fetcher import is_valid_accession_shape
        if not is_valid_accession_shape(request.accession_number):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid accession number shape: {request.accession_number!r}. "
                    "Expected 18 digits or `\\d{10}-\\d{2}-\\d{6}` (e.g. "
                    "`0000320193-23-000106`)."
                ),
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
        from src.llm_provider import set_user_keys
        from src.task3_sec.pipeline import extract_10k as run_pipeline

        # Per-request user keys — get_llm reads them from contextvars when its
        # explicit user_*_key params are empty. See src/llm_provider.py.
        set_user_keys(
            openrouter=request.model.user_openrouter_key,
            nvidia=request.model.user_nvidia_key,
        )
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
            max_cost_usd=request.max_cost_usd,
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


@router.post("/stream")
async def stream_extract_10k(request: SECExtractionRequest):
    """SSE stream for live SEC extraction progress.

    Reviewer-facing milestones:
        stream_start      {trace_id}
        pipeline_start    {cik, accession, model, use_vision, skip_llm}
        fetch_start       {url}
        fetch_done        {bytes, company, form_type, filing_date}
        stage1_start      {stage}
        stage1_done       {items_found, avg_confidence, format, duration_ms}
        stage2_start      {model, use_vision, current_confidence}
        stage2_done       {items_found, llm_calls, duration_ms}  OR
        stage2_skipped    {reason, avg_confidence}                OR
        stage2_failed     {error}
        stage3_start/done {overall_valid, issue_count}
        stage4_start/done {xbrl_status, checks}                   OR  stage4_failed
        pipeline_complete {items, rule_only, llm_refined, cost_usd, status_counts}
        error             {category, user_message, suggested_action, raw_error}
        stream_end        {trace_id}

    Long filings + LLM refinement can take 60+ seconds; streaming lets the
    UI show what's happening rather than spinner-and-wait.
    """
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from src.shared.llm_errors import classify_llm_error, to_dict

    trace_id = generate_trace_id()
    if not request.cik and not request.filing_url:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'cik' (with optional 'accession_number') or 'filing_url'",
        )
    if request.accession_number:
        from src.task3_sec.fetcher import is_valid_accession_shape
        if not is_valid_accession_shape(request.accession_number):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid accession number shape: {request.accession_number!r}. "
                    "Expected `\\d{10}-\\d{2}-\\d{6}` or 18 digits."
                ),
            )

    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def progress_callback(event: dict) -> None:
        # Non-blocking — if the consumer disconnected mid-extraction, we
        # don't want the pipeline to wedge waiting for queue drain.
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("sse_queue_full_dropping_event", event=event.get("event"))

    async def run_pipeline() -> None:
        try:
            from src.llm_provider import set_user_keys
            from src.task3_sec.pipeline import extract_10k as run

            set_user_keys(
                openrouter=request.model.user_openrouter_key,
                nvidia=request.model.user_nvidia_key,
            )
            result = await run(
                cik=request.cik,
                accession_number=request.accession_number,
                filing_url=request.filing_url,
                model_name=request.model.model_id,
                user_api_key=request.model.user_openrouter_key,
                skip_llm=request.skip_llm,
                skip_xbrl=request.skip_xbrl,
                use_vision=request.use_vision,
                force_llm=getattr(request, "force_llm", False),
                max_cost_usd=getattr(request, "max_cost_usd", None),
                progress_callback=progress_callback,
                trace_id=trace_id,
            )
            # Embed final ExtractionResult in the stream so the FE doesn't
            # need a redundant /extract call (was doubling latency on slow
            # LLM-refine paths). Mirrors Task 1's stream-result pattern.
            await queue.put(
                {
                    "event": "result",
                    "trace_id": trace_id,
                    "result": result.model_dump(mode="json"),
                }
            )
        except Exception as e:
            err = to_dict(classify_llm_error(e))
            err["trace_id"] = trace_id
            await queue.put({"event": "error", **err})
        finally:
            await queue.put({"event": "stream_end", "trace_id": trace_id})

    runner = asyncio.create_task(run_pipeline())

    async def event_generator():
        yield f"data: {_json.dumps({'event': 'stream_start', 'trace_id': trace_id})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {_json.dumps(event)}\n\n"
            if event.get("event") == "stream_end":
                break
        if not runner.done():
            runner.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
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
