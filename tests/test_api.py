"""Tests for FastAPI application endpoints."""

import httpx
import pytest

from src.main import app
from src.task3_sec.schemas import (
    ExtractedItem,
    ExtractionResult,
    FilingMetadata,
    ItemStatus,
    ProcessingMetadata,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    """Async ASGI client for FastAPI endpoint tests."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


class TestHealthAndSystem:
    """Test system endpoints."""

    async def test_health_check(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "tasks" in data

    async def test_list_models(self, client):
        response = await client.get("/api/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        models = data["models"]
        assert len(models) >= 7
        # Check both providers present
        providers = {m["provider"] for m in models}
        assert "openrouter" in providers
        assert "nvidia" in providers

    async def test_metrics(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_calls" in data

    async def test_dashboard(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        assert "Signal-Foundry" in response.text


class TestTask1Routes:
    """Test CI/CD Skills API routes."""

    async def test_list_skills(self, client):
        response = await client.get("/api/v1/skills/list")
        assert response.status_code == 200
        data = response.json()
        assert len(data["skills"]) == 4

    async def test_run_skill(self, client, monkeypatch):
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType

        async def mock_engine(request, trace_id):
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={
                    "skill": "lint-and-test",
                    "repo_url": request.repo_url,
                    "branch": "main",
                    "commit_sha": "abc123",
                    "summary": "All lint checks passed, 10 tests ran successfully.",
                },
            )

        monkeypatch.setattr("src.task1_cicd.skill_engine.run_skill", mock_engine)

        response = await client.post(
            "/api/v1/skills/run",
            json={
                "repo_url": "https://github.com/tychen5/signal-foundry",
                "skill_name": "lint-and-test",
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    async def test_run_invalid_skill(self, client):
        response = await client.post(
            "/api/v1/skills/run",
            json={
                "repo_url": "https://github.com/test/repo",
                "skill_name": "invalid-skill",
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        )
        assert response.status_code == 400


class TestTask2Routes:
    """Test Browser Agent API routes."""

    async def test_execute_task(self, client, monkeypatch):
        from src.task2_browser.schemas import AgentResult

        async def fake_run(self, **kwargs):
            return AgentResult(
                trace_id="test-123",
                task_description="Search Wikipedia for AI",
                target_url="https://www.wikipedia.org",
                status="success",
                total_steps=3,
                final_answer="Artificial intelligence is...",
                self_corrections=0,
            )

        monkeypatch.setattr("src.task2_browser.agent.BrowserAgent.run", fake_run)

        response = await client.post(
            "/api/v1/browser/execute",
            json={
                "task_description": "Search Wikipedia for AI",
                "target_url": "https://www.wikipedia.org",
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["result"]["total_steps"] == 3

    async def test_execute_rejects_bad_model_shape(self, client):
        response = await client.post(
            "/api/v1/browser/execute",
            json={
                "task_description": "Open example.com",
                "model": {"model_id": "gpt-5.5"},
            },
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["stage"] == "input_validation"
        assert detail["category"] == "bad_model_id_shape"
        assert detail["error_field"] == "model.model_id"

    async def test_execute_returns_stage_attributed_llm_error(self, client, monkeypatch):
        from src.shared.llm_errors import LLMStageError

        async def fake_run(self, **kwargs):
            raise LLMStageError(
                "provider rejected key",
                stage="browser_plan",
                provider="nvidia",
                model_id="moonshotai/kimi-k2.6",
                original=RuntimeError("Error code: 401 - Invalid API key"),
            )

        monkeypatch.setattr("src.task2_browser.agent.BrowserAgent.run", fake_run)

        response = await client.post(
            "/api/v1/browser/execute",
            json={
                "task_description": "Open example.com",
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        err = data["cost_metadata"]["llm_error"]
        assert err["stage"] == "browser_plan"
        assert err["status_code"] == 401
        assert err["status_label"] == "401 Unauthorized"

    async def test_stream_task_emits_sse_events(self, client, monkeypatch):
        """SSE stream endpoint emits stream_start, milestone events, and stream_end."""
        from src.task2_browser.schemas import AgentResult

        async def fake_run(self, **kwargs):
            # Push a couple of events through the progress callback to simulate
            # a real run, then return.
            cb = self.progress_callback
            if cb is not None:
                await cb({"event": "phase_start", "phase": "plan", "model": "test"})
                await cb({"event": "phase_done", "phase": "plan", "plan_steps": 2})
                await cb({"event": "step_start", "step": 1, "action": "navigate", "target": "wiki"})
                await cb(
                    {
                        "event": "step_done",
                        "step": 1,
                        "url": "https://wiki/",
                        "healer": False,
                        "diagnosis": "",
                        "confidence": 0.95,
                        "error": "",
                    }
                )
                await cb(
                    {
                        "event": "agent_complete",
                        "status": "success",
                        "steps": 1,
                        "self_corrections": 0,
                        "cost_usd": 0.0,
                        "duration_ms": 100,
                        "answer": "ok",
                        "failure_modes": [],
                    }
                )
            return AgentResult(
                trace_id="test-stream",
                task_description="test",
                target_url="",
                status="success",
                total_steps=1,
                final_answer="ok",
            )

        monkeypatch.setattr("src.task2_browser.agent.BrowserAgent.run", fake_run)

        async with client.stream(
            "POST",
            "/api/v1/browser/stream",
            json={
                "task_description": "test",
                "max_steps": 5,
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            chunks = []
            async for line in resp.aiter_lines():
                chunks.append(line)
                # Read enough events; stop once we see stream_end to avoid infinite poll
                if "stream_end" in line or "agent_complete" in line:
                    if len([c for c in chunks if c.startswith("data:")]) >= 6:
                        break

        events = [c for c in chunks if c.startswith("data:")]
        assert any("stream_start" in e for e in events)
        assert any("phase_done" in e for e in events)
        assert any("step_done" in e for e in events)
        assert any("agent_complete" in e for e in events)


class TestTask3Routes:
    """Test SEC 10-K Extraction API routes."""

    async def test_extract_with_cik(self, client, monkeypatch):
        async def fake_extract_10k(**kwargs):
            return ExtractionResult(
                filing_metadata=FilingMetadata(
                    cik=kwargs["cik"],
                    accession_number=kwargs["accession_number"],
                    filing_url="https://www.sec.gov/Archives/edgar/data/320193/example/aapl.htm",
                ),
                items=[
                    ExtractedItem(
                        part="I",
                        item_number="1",
                        item_title="Business",
                        content_text="Business content.",
                        char_range=[0, 17],
                        status=ItemStatus.EXTRACTED,
                        confidence=0.99,
                    )
                ],
                processing_metadata=ProcessingMetadata(
                    total_latency_ms=12.0,
                    stages_used=["rule_based", "validation"],
                    validation_report={"overall_valid": True},
                ),
            )

        monkeypatch.setattr("src.task3_sec.pipeline.extract_10k", fake_extract_10k)

        response = await client.post(
            "/api/v1/sec/extract",
            json={
                "cik": "0000320193",
                "accession_number": "0000320193-23-000106",
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["result"]["filing_metadata"]["cik"] == "0000320193"
        assert data["cost_metadata"]["validation_overall_valid"] is True

    async def test_extract_missing_input(self, client):
        response = await client.post(
            "/api/v1/sec/extract",
            json={},
        )
        assert response.status_code == 400

    async def test_stream_extract_emits_pipeline_events(self, client, monkeypatch):
        """SSE endpoint streams pipeline_start → fetch → stage1 → stage2 →
        pipeline_complete events through the progress callback."""

        async def fake_extract_10k(**kwargs):
            cb = kwargs.get("progress_callback")
            if cb:
                await cb({"event": "pipeline_start", "cik": kwargs.get("cik", "")})
                await cb({"event": "fetch_start", "url": "https://test/10k.htm"})
                await cb({"event": "fetch_done", "bytes": 12345, "company": "Apple Inc."})
                await cb({"event": "stage1_start", "stage": "rule_parse"})
                await cb({"event": "stage1_done", "items_found": 22, "avg_confidence": 0.95})
                await cb({"event": "stage2_skipped", "reason": "rule_parser_confident"})
                await cb({"event": "stage3_start", "stage": "validation"})
                await cb({"event": "stage3_done", "overall_valid": True})
                await cb(
                    {
                        "event": "pipeline_complete",
                        "items": 23,
                        "rule_only": 23,
                        "llm_refined": 0,
                        "cost_usd": 0.0,
                        "stages": ["rule_based", "validation"],
                        "status_counts": {"extracted": 14, "incorporated_by_reference": 6, "not_applicable": 3},
                    }
                )
            # Return value isn't used by the stream consumer
            return ExtractionResult(
                filing_metadata=FilingMetadata(
                    cik=kwargs.get("cik", ""),
                    accession_number=kwargs.get("accession_number", ""),
                ),
                items=[],
                processing_metadata=ProcessingMetadata(),
            )

        monkeypatch.setattr("src.task3_sec.pipeline.extract_10k", fake_extract_10k)

        async with client.stream(
            "POST",
            "/api/v1/sec/extract" + "/" if False else "/api/v1/sec/stream",
            json={
                "cik": "0000320193",
                "accession_number": "0000320193-23-000106",
                "model": {
                    "model_id": "moonshotai/kimi-k2.6",
                    "user_nvidia_key": "nvapi-test",
                },
            },
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            chunks: list[str] = []
            async for line in resp.aiter_lines():
                chunks.append(line)
                if "stream_end" in line and len([c for c in chunks if c.startswith("data:")]) >= 6:
                    break

        events = [c for c in chunks if c.startswith("data:")]
        assert any("stream_start" in e for e in events)
        assert any("fetch_done" in e for e in events)
        assert any("stage1_done" in e for e in events)
        assert any("pipeline_complete" in e for e in events)
