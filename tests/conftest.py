"""Shared fixtures. DB-backed tests need a running Postgres (see docker-compose.yml) and
are skipped automatically when one isn't reachable, so the rest of the suite still runs
without Docker.
"""

from __future__ import annotations

import psycopg
import pytest

from orswater.db import connect


@pytest.fixture
def db_conn():
    """A live connection whose transaction is rolled back after the test, so anything a
    test inserts never touches the real ingested data. Skips the test if Postgres isn't
    reachable rather than failing the whole suite."""
    try:
        conn = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not reachable (is `docker compose up -d` running?)")

    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
