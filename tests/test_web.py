"""Tests for the FastAPI app (M6). Uses FastAPI's TestClient (httpx underneath, already a
dependency) against a real DB connection -- no mocking of orswater.answer.answer, so these
also exercise the real deterministic backend end to end. Skipped, like the DB-backed tests
elsewhere, when Postgres isn't reachable.
"""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

from orswater.db import connect
from orswater.web import app


class _NonClosing:
    """Wraps a connection so web.py's ``conn.close()`` is a no-op -- used to hand it the
    test's own ``db_conn`` (whose rollback/close is the fixture's job) without web.py
    closing it out from under that fixture's teardown."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


@pytest.fixture
def client():
    try:
        connect().close()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not reachable (is `docker compose up -d` running?)")
    return TestClient(app)


def test_ask_returns_deterministic_answer_with_citation_and_url(client, monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    response = client.post("/api/ask", json={"question": "What does ORS 537.545 say about exempt uses?"})
    assert response.status_code == 200

    body = response.json()
    assert body["backend"] == "deterministic"
    assert "not legal advice" in body["text"].lower()

    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["section_number"] == "537.545"
    assert citation["url"] == "https://www.oregonlegislature.gov/bills_laws/ors/ors537.html"

    assert len(body["retrieved_sections"]) >= 1
    assert body["retrieved_sections"][0]["section_number"] == "537.545"


def test_ask_defaults_groups_to_empty_list(client, monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    response = client.post("/api/ask", json={"question": "Can I dig a well?"})
    assert response.status_code == 200


def test_ask_with_no_results_returns_the_no_results_text(client, monkeypatch, db_conn):
    """Empty the corpus inside db_conn's own (rolled-back-after-the-test) transaction, then
    point web.py at that same connection so the deletion is visible without ever committing
    it -- the real ingested data is untouched once the db_conn fixture rolls back."""
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    db_conn.execute("DELETE FROM sections")

    import orswater.web as web_module

    monkeypatch.setattr(web_module, "connect", lambda: _NonClosing(db_conn))

    response = client.post("/api/ask", json={"question": "Can I dig a well?"})
    assert response.status_code == 200
    body = response.json()
    assert body["text"].startswith("No ORS sections")
    assert body["citations"] == []
    assert body["retrieved_sections"] == []


def test_anthropic_backend_without_a_real_key_returns_503(client, monkeypatch):
    monkeypatch.setenv("ANSWER_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    response = client.post("/api/ask", json={"question": "What does ORS 537.545 say about exempt uses?"})
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
