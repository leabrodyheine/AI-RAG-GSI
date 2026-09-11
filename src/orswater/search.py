"""``search(question, user_groups)`` -- the one swappable retrieval seam.

Everything downstream (answer.py, the web API) only ever calls this function. To point the
prototype at a different corpus later (e.g. a company's M365 / file-server documents), this
is the only file that needs to change.

Permission filtering happens **inside the SQL** in every branch below -- never after
retrieval, never via the prompt, per the README's rule. A row with ``allowed_groups = '{}'``
is public; otherwise the row is only visible when it overlaps ``user_groups``.

Ranking: a literal ORS citation in the question (e.g. "537.130") is resolved directly, since
that's an exact, unambiguous request -- no need to guess via search. Otherwise, full-text
search (top 20) and vector search (top 20) are merged with Reciprocal Rank Fusion (k=60, the
standard default from the original RRF paper) and the top 8 are returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg

from .embed import embed_query

CITATION_RE = re.compile(r"\b(5[3-4]\d)\.(\d{3,4})\b")
FTS_LIMIT = 20
VECTOR_LIMIT = 20
RESULT_LIMIT = 8
RRF_K = 60

# Appended to every WHERE clause. psycopg adapts a Python list[str] to a Postgres text[].
_PERMISSION_SQL = "(allowed_groups = '{}' OR allowed_groups && %(user_groups)s::text[])"


@dataclass(frozen=True)
class Result:
    section_number: str
    heading: str
    text: str
    url: str
    # Cosine distance between the question embedding and this section's embedding (0 =
    # identical, larger = less similar). None for a direct ORS-citation match, which is
    # exact by construction and has no meaningful distance to compute.
    distance: float | None = None


def _row_to_result(row: tuple, *, distance: float | None = None) -> Result:
    section_number, heading, text, source_url = row
    return Result(
        section_number=section_number, heading=heading, text=text, url=source_url, distance=distance
    )


def _find_citation(question: str) -> str | None:
    """Return the first ORS section number (e.g. "537.130") literally present in the
    question, or None. Chapters 536-540 only -- this prototype's corpus."""
    match = CITATION_RE.search(question)
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def _lookup_citation(conn: psycopg.Connection, section_number: str, user_groups: list[str]) -> Result | None:
    row = conn.execute(
        f"""
        SELECT section_number, heading, text, source_url
        FROM sections
        WHERE section_number = %(section_number)s AND {_PERMISSION_SQL}
        """,
        {"section_number": section_number, "user_groups": user_groups},
    ).fetchone()
    return _row_to_result(row) if row is not None else None


def _fts_search(conn: psycopg.Connection, question: str, user_groups: list[str]) -> list[str]:
    """Return up to FTS_LIMIT section_numbers ranked by full-text relevance."""
    rows = conn.execute(
        f"""
        SELECT section_number
        FROM sections, websearch_to_tsquery('english', %(question)s) query
        WHERE fts @@ query AND {_PERMISSION_SQL}
        ORDER BY ts_rank_cd(fts, query) DESC
        LIMIT %(limit)s
        """,
        {"question": question, "user_groups": user_groups, "limit": FTS_LIMIT},
    ).fetchall()
    return [r[0] for r in rows]


def _vector_search(
    conn: psycopg.Connection, query_embedding: list[float], user_groups: list[str]
) -> list[str]:
    """Return up to VECTOR_LIMIT section_numbers ranked by embedding cosine distance."""
    rows = conn.execute(
        f"""
        SELECT section_number
        FROM sections
        WHERE {_PERMISSION_SQL}
        ORDER BY embedding <=> %(embedding)s::vector
        LIMIT %(limit)s
        """,
        {"embedding": query_embedding, "user_groups": user_groups, "limit": VECTOR_LIMIT},
    ).fetchall()
    return [r[0] for r in rows]


def _reciprocal_rank_fusion(ranked_lists: list[list[str]], *, k: int = RRF_K) -> list[str]:
    """Merge several ranked lists of the same kind of key into one ranking.

    Each list contributes ``1 / (k + rank)`` (rank is 1-based) to every key it contains;
    scores are summed across lists and the result is sorted by total score, descending.
    """
    scores: dict[str, float] = {}
    order: list[str] = []  # first-seen order, used only to make ties deterministic
    for ranked in ranked_lists:
        for rank, key in enumerate(ranked, start=1):
            if key not in scores:
                order.append(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    return sorted(order, key=lambda key: scores[key], reverse=True)


def _fetch_results(
    conn: psycopg.Connection,
    section_numbers: list[str],
    user_groups: list[str],
    query_embedding: list[float],
) -> list[Result]:
    """Fetch full rows for a list of section numbers, permission-filtered, preserving order.
    Each row's cosine distance to ``query_embedding`` is attached, regardless of whether it
    was originally found by full-text or vector search -- a single, comparable relevance
    signal callers (the deterministic answer backend) can use to judge match quality."""
    if not section_numbers:
        return []
    rows = conn.execute(
        f"""
        SELECT section_number, heading, text, source_url, embedding <=> %(embedding)s::vector AS distance
        FROM sections
        WHERE section_number = ANY(%(numbers)s) AND {_PERMISSION_SQL}
        """,
        {"numbers": section_numbers, "user_groups": user_groups, "embedding": query_embedding},
    ).fetchall()
    by_number = {r[0]: _row_to_result(r[:4], distance=r[4]) for r in rows}
    return [by_number[n] for n in section_numbers if n in by_number]


def search(conn: psycopg.Connection, question: str, user_groups: list[str]) -> list[Result]:
    """Return up to RESULT_LIMIT sections relevant to ``question``, visible to ``user_groups``.

    ``conn`` is a live psycopg connection (see db.connect). Passing it in, rather than opening
    one internally, keeps this function easy to call from a request-scoped connection later.
    """
    citation = _find_citation(question)
    if citation is not None:
        hit = _lookup_citation(conn, citation, user_groups)
        if hit is not None:
            return [hit]
        # Citation present but not visible/found (wrong chapter, excluded, or permission-
        # filtered) -- fall through to ordinary search rather than returning nothing.

    query_embedding = embed_query(question)
    fts_ranked = _fts_search(conn, question, user_groups)
    vector_ranked = _vector_search(conn, query_embedding, user_groups)
    merged = _reciprocal_rank_fusion([fts_ranked, vector_ranked])[:RESULT_LIMIT]
    return _fetch_results(conn, merged, user_groups, query_embedding)
