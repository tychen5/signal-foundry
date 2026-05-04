"""Tests for FastAPI application endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


class TestHealthAndSystem:
    """Test system endpoints."""

    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "tasks" in data

    def test_list_models(self):
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        models = data["models"]
        assert len(models) >= 7
        # Check both providers present
        providers = {m["provider"] for m in models}
        assert "openrouter" in providers
        assert "nvidia" in providers

    def test_metrics(self):
        response = client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_calls" in data

    def test_dashboard(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Signal-Foundry" in response.text


class TestTask1Routes:
    """Test CI/CD Skills API routes."""

    def test_list_skills(self):
        response = client.get("/api/v1/skills/list")
        assert response.status_code == 200
        data = response.json()
        assert len(data["skills"]) == 4

    def test_run_skill(self):
        response = client.post(
            "/api/v1/skills/run",
            json={
                "repo_url": "https://github.com/tychen5/signal-foundry",
                "skill_name": "lint-and-test",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_run_invalid_skill(self):
        response = client.post(
            "/api/v1/skills/run",
            json={
                "repo_url": "https://github.com/test/repo",
                "skill_name": "invalid-skill",
            },
        )
        assert response.status_code == 400


class TestTask2Routes:
    """Test Browser Agent API routes."""

    def test_execute_task(self):
        response = client.post(
            "/api/v1/browser/execute",
            json={
                "task_description": "Search Wikipedia for AI",
                "target_url": "https://www.wikipedia.org",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


class TestTask3Routes:
    """Test SEC 10-K Extraction API routes."""

    def test_extract_with_cik(self):
        response = client.post(
            "/api/v1/sec/extract",
            json={
                "cik": "0000320193",
                "accession_number": "0000320193-23-000106",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_extract_missing_input(self):
        response = client.post(
            "/api/v1/sec/extract",
            json={},
        )
        assert response.status_code == 400
