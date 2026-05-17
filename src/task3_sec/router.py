"""
Task 3 Router: SEC 10-K Extraction API.

Full production endpoints for extracting structured item-level data from SEC 10-K filings.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.llm_errors import LLMStageError, classify_with_stage
from src.shared.llm_validation import (
    validate_model_selection,
    validation_error_to_envelope,
)
from src.shared.logger import generate_trace_id, get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, ModelSelectionRequest, TaskType

router = APIRouter()
logger = get_logger("task3_router")


def _validate_llm_model_or_400(model: object, *, requires_llm: bool) -> str:
    """Validate the model block only when this request may call Stage 2 LLM."""
    if not requires_llm:
        return getattr(model, "provider", None) or ""
    resolution = validate_model_selection(model)
    if not resolution.valid:
        raise HTTPException(
            status_code=400,
            detail=validation_error_to_envelope(resolution),
        )
    return resolution.provider or ""


def _failed_llm_result(
    exc: object,
    *,
    trace_id: str,
    stage: str,
    provider: str,
    model_id: str,
) -> ExecutionResult:
    envelope = (
        exc.to_envelope()
        if isinstance(exc, LLMStageError)
        else classify_with_stage(exc, stage=stage, provider=provider, model_id=model_id)
    )
    envelope["provider"] = envelope.get("provider") or provider
    envelope["model_id"] = envelope.get("model_id") or model_id
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        task=TaskType.SEC_EXTRACTION,
        trace_id=trace_id,
        error=envelope.get("user_message") or envelope.get("raw_error"),
        failure_type=FailureType.LLM_ERROR,
        cost_metadata={"llm_error": envelope},
    )


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

    requires_llm = request.force_llm or not request.skip_llm
    provider = _validate_llm_model_or_400(request.model, requires_llm=requires_llm)
    from src.llm_provider import clear_user_keys, set_user_keys

    try:
        from src.task3_sec.pipeline import extract_10k as run_pipeline

        # Per-request user keys — get_llm reads them from contextvars when its
        # explicit user_*_key params are empty. See src/llm_provider.py.
        set_user_keys(
            openrouter=request.model.user_openrouter_key,
            nvidia=request.model.user_nvidia_key,
            provider_hint=provider or None,
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

    except LLMStageError as e:
        logger.warning("extraction_llm_error", error=str(e), trace_id=trace_id)
        return _failed_llm_result(
            e,
            trace_id=trace_id,
            stage=e.stage,
            provider=provider,
            model_id=request.model.model_id,
        )
    except ValueError as e:
        logger.warning("extraction_validation_error", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error("extraction_failed", error=str(e), trace_id=trace_id)
        envelope = classify_with_stage(
            e,
            stage="sec_pipeline",
            provider=provider,
            model_id=request.model.model_id,
        )
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.SEC_EXTRACTION,
            trace_id=trace_id,
            error=str(e),
            failure_type=FailureType.PARSING_ERROR,
            cost_metadata={"llm_error": envelope},
        )
    finally:
        clear_user_keys()


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

    requires_llm = request.force_llm or not request.skip_llm
    provider = _validate_llm_model_or_400(request.model, requires_llm=requires_llm)
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
            from src.llm_provider import clear_user_keys, set_user_keys
            from src.task3_sec.pipeline import extract_10k as run

            set_user_keys(
                openrouter=request.model.user_openrouter_key,
                nvidia=request.model.user_nvidia_key,
                provider_hint=provider or None,
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
        except LLMStageError as e:
            err = e.to_envelope()
            err["provider"] = err.get("provider") or provider
            err["model_id"] = err.get("model_id") or request.model.model_id
            err["trace_id"] = trace_id
            await queue.put({"event": "error", **err})
        except Exception as e:
            err = to_dict(classify_llm_error(e))
            err["stage"] = "sec_pipeline"
            err["provider"] = provider
            err["model_id"] = request.model.model_id
            err["trace_id"] = trace_id
            await queue.put({"event": "error", **err})
        finally:
            try:
                clear_user_keys()
            except Exception:
                pass
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


def _validate_cik_or_400(cik: str) -> str:
    """Validate CIK is digit-string-like (after stripping leading zeros).

    Raises HTTPException(400) for non-numeric inputs. Returns normalised
    10-digit padded CIK on success.
    """
    import re

    if not cik:
        raise HTTPException(
            status_code=400,
            detail="cik parameter is required",
        )
    digits = re.sub(r"\D", "", cik)
    if not digits or len(digits) > 10:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid CIK '{cik}'. CIK must be a number (1-10 digits), e.g. "
                "'320193' or '0000320193' for Apple Inc."
            ),
        )
    return digits.zfill(10)


@router.get("/filings/{cik}")
async def list_filings(cik: str, filing_type: str = "10-K", limit: int = 10):
    """
    List recent filings for a company by CIK.

    Useful for finding accession numbers to pass to /extract.
    """
    cik_padded = _validate_cik_or_400(cik)
    try:
        from src.task3_sec.fetcher import fetch_company_metadata

        metadata = await fetch_company_metadata(cik_padded)

        # Filter by form type
        filings = [
            f
            for f in metadata.get("filings", [])
            if f.get("form", "") == filing_type or (filing_type == "10-K" and f.get("form", "") == "10-K/A")
        ][:limit]

        return {
            "cik": metadata.get("cik", cik_padded),
            "company_name": metadata.get("company_name", ""),
            "tickers": metadata.get("tickers", []),
            "filing_type": filing_type,
            "count": len(filings),
            "filings": filings,
        }

    except HTTPException:
        raise
    except Exception as e:
        # SEC API 404 (CIK doesn't exist) → return clean 404 with no
        # leaked URLs / internal error details. Other errors → 502
        # (upstream issue) with sanitised message.
        err_str = str(e)
        logger.warning("filing_list_failed", error=err_str, cik=cik_padded)
        if "404" in err_str or "Not Found" in err_str:
            raise HTTPException(
                status_code=404,
                detail=f"No SEC filings found for CIK {cik_padded}. "
                "Verify the company exists at https://www.sec.gov/cgi-bin/browse-edgar.",
            )
        raise HTTPException(
            status_code=502,
            detail=(
                f"SEC EDGAR is temporarily unreachable for CIK {cik_padded}. "
                "Try again in a moment."
            ),
        )


@router.get("/company/{cik}")
async def company_info(cik: str):
    """Get company metadata from SEC EDGAR."""
    cik_padded = _validate_cik_or_400(cik)
    try:
        from src.task3_sec.fetcher import fetch_company_metadata

        metadata = await fetch_company_metadata(cik_padded)
        return {
            "cik": metadata.get("cik", cik_padded),
            "company_name": metadata.get("company_name", ""),
            "entity_type": metadata.get("entity_type", ""),
            "sic": metadata.get("sic", ""),
            "tickers": metadata.get("tickers", []),
            "exchanges": metadata.get("exchanges", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        logger.warning("company_info_failed", error=err_str, cik=cik_padded)
        if "404" in err_str or "Not Found" in err_str:
            raise HTTPException(
                status_code=404,
                detail=f"No SEC company found for CIK {cik_padded}.",
            )
        raise HTTPException(
            status_code=502,
            detail=f"SEC EDGAR is temporarily unreachable for CIK {cik_padded}.",
        )
