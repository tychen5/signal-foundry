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
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["result"]["total_steps"] == 3


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
