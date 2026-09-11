"""Postgres access: a plain psycopg connection with pgvector registered, plus schema setup.

No ORM. Callers write SQL directly.
"""

from __future__ import annotations

import pathlib

import psycopg
from pgvector.psycopg import register_vector

from .config import load_config

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def connect(database_url: str | None = None, *, register: bool = True) -> psycopg.Connection:
    """Open a connection. ``register=False`` skips pgvector type registration, which is
    required on a fresh database where the ``vector`` extension does not exist yet."""
    url = database_url or load_config().database_url
    conn = psycopg.connect(url)
    if register:
        register_vector(conn)
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()


def main() -> None:
    with connect(register=False) as conn:
        apply_schema(conn)
    # Re-connect with registration to prove the extension and vector type are usable.
    with connect() as conn:
        row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    print(f"schema applied from {SCHEMA_PATH}; pgvector {row[0] if row else 'MISSING'}")


if __name__ == "__main__":
    main()
