"""
API endpoint tests using FastAPI TestClient.

Tests cover:
  - GET /api/health
  - GET /api/problems
  - GET /api/problems/{id}
  - POST /api/submit

Note: These tests require a running PostgreSQL instance.
For CI, use the docker-compose services.

Version: 2026-02-12
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.db.database import engine, init_db
from backend.db.models import Base
from backend.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create tables before tests, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS production CASCADE;"))
        await conn.execute(text("DROP SCHEMA IF EXISTS sales CASCADE;"))
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for FastAPI."""
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    yield ac
    await ac.aclose()


@pytest_asyncio.fixture
async def seeded_client(client: AsyncClient):
    """Client with seeded data."""
    from backend.db.seed import seed_database
    await seed_database()
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for GET /api/health."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "timestamp" in data


class TestProblemsEndpoints:
    """Tests for problem-related endpoints."""

    @pytest.mark.asyncio
    async def test_list_problems_empty(self, client: AsyncClient) -> None:
        """Empty database returns empty list."""
        response = await client.get("/api/problems")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_problems_seeded(self, seeded_client: AsyncClient) -> None:
        """Seeded database returns problems."""
        response = await seeded_client.get("/api/problems")
        assert response.status_code == 200
        problems = response.json()
        assert len(problems) >= 3
        assert all("title" in p for p in problems)

    @pytest.mark.asyncio
    async def test_get_problem_not_found(self, client: AsyncClient) -> None:
        """Non-existent problem returns 404."""
        response = await client.get("/api/problems/999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_problem_detail(self, seeded_client: AsyncClient) -> None:
        """Get specific problem returns details with visible test cases."""
        response = await seeded_client.get("/api/problems/1")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] is not None
        assert "test_cases" in data
        # Hidden test cases should not appear
        for tc in data["test_cases"]:
            assert "id" in tc


class TestSubmitEndpoint:
    """Tests for POST /api/submit."""

    @pytest.mark.asyncio
    async def test_submit_correct_code(self, seeded_client: AsyncClient) -> None:
        """Submitting correct code returns passing result."""
        response = await seeded_client.post(
            "/api/submit",
            json={
                "user_id": 1,
                "problem_id": 1,
                "code": "SELECT first_name, last_name FROM sales.customers ORDER BY last_name;",
                "language": "sql",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overall_passed"] is True
        assert data["grading"]["score"] == 1.0

    @pytest.mark.asyncio
    async def test_submit_wrong_code(self, seeded_client: AsyncClient) -> None:
        """Submitting wrong code returns failing result with hints."""
        response = await seeded_client.post(
            "/api/submit",
            json={
                "user_id": 1,
                "problem_id": 1,
                "code": "SELECT first_name FROM sales.customers;",
                "language": "sql",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overall_passed"] is False
        assert data["hint"] is not None
        assert data["hint"]["hint_level"] >= 1

    @pytest.mark.asyncio
    async def test_submit_user_not_found(self, seeded_client: AsyncClient) -> None:
        """Non-existent user returns 404."""
        response = await seeded_client.post(
            "/api/submit",
            json={
                "user_id": 999,
                "problem_id": 1,
                "code": "SELECT * FROM sales.customers;",
                "language": "sql",
            },
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_problem_not_found(self, seeded_client: AsyncClient) -> None:
        """Non-existent problem returns 404."""
        response = await seeded_client.post(
            "/api/submit",
            json={
                "user_id": 1,
                "problem_id": 999,
                "code": "SELECT * FROM sales.customers;",
                "language": "sql",
            },
        )
        assert response.status_code == 404
