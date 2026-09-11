"""Unit tests for the pure-Python pieces of orswater.search, plus DB-backed tests for
citation lookup and SQL-only permission filtering. The DB tests insert their own throwaway
rows and roll back afterward (see conftest.db_conn) -- they never depend on or mutate the
real ingested ORS data, except for one read-only check against the README's own citation
example (537.545, which Milestone 2's real ingest run confirmed is present).
"""

from __future__ import annotations

from orswater.embed import embed_passages
from orswater.search import _find_citation, _reciprocal_rank_fusion, search

# ---------------------------------------------------------------------------
# Pure-Python: citation detection
# ---------------------------------------------------------------------------


def test_find_citation_extracts_the_first_ors_number():
    assert _find_citation("What does 537.130 require before diverting water?") == "537.130"


def test_find_citation_ignores_numbers_outside_the_ors_chapter_range():
    # 123.456 isn't a chapter 536-540 citation -- should not match.
    assert _find_citation("See docket 123.456 for background.") is None


def test_find_citation_returns_none_when_absent():
    assert _find_citation("Can I dig a well on my property?") is None


# ---------------------------------------------------------------------------
# Pure-Python: reciprocal rank fusion
# ---------------------------------------------------------------------------


def test_rrf_prefers_a_key_ranked_highly_in_both_lists():
    fts = ["a", "b", "c"]
    vector = ["b", "a", "c"]
    merged = _reciprocal_rank_fusion([fts, vector])
    # "a" and "b" are both top-2 in both lists; "c" is last in both -- "c" must rank last.
    assert merged[-1] == "c"
    assert set(merged[:2]) == {"a", "b"}


def test_rrf_keeps_a_key_that_appears_in_only_one_list():
    fts = ["a", "b"]
    vector = ["c", "d"]
    merged = _reciprocal_rank_fusion([fts, vector])
    assert set(merged) == {"a", "b", "c", "d"}


def test_rrf_ranks_a_key_found_by_both_methods_above_one_found_by_only_one():
    fts = ["shared", "fts_only"]
    vector = ["shared", "vector_only"]
    merged = _reciprocal_rank_fusion([fts, vector])
    assert merged[0] == "shared"


# ---------------------------------------------------------------------------
# DB-backed: citation lookup takes priority over ranked search
# ---------------------------------------------------------------------------


def test_citation_in_question_returns_that_section_first(db_conn):
    results = search(db_conn, "What does ORS 537.545 say about exempt uses?", user_groups=[])
    assert len(results) == 1
    assert results[0].section_number == "537.545"
    assert results[0].heading == "Exempt uses; map; filing of use; fee; rules."


def test_unrecognized_question_falls_back_to_ranked_search(db_conn):
    results = search(db_conn, "Can I dig a well on my property without a permit?", user_groups=[])
    assert 0 < len(results) <= 8
    assert all(r.section_number for r in results)
    # A relevance signal (used by the deterministic answer backend), not a filter here --
    # search() itself still returns every ranked-search result regardless of distance.
    assert all(isinstance(r.distance, float) for r in results)


def test_citation_match_has_no_distance(db_conn):
    # An exact ORS-citation match is confident by construction -- no embedding distance
    # is computed for it, distinguishing it from a ranked-search result.
    results = search(db_conn, "What does ORS 537.545 say about exempt uses?", user_groups=[])
    assert results[0].distance is None


# ---------------------------------------------------------------------------
# DB-backed: permission filtering happens inside the SQL, never after retrieval
# ---------------------------------------------------------------------------


TEST_QUESTION = "zzyzxquorp irrigation"


def _insert_restricted_section(conn, *, section_number: str, allowed_groups: list[str]):
    # "zzyzxquorp" is a made-up word that appears nowhere in the real ORS text, so a
    # full-text search for it can only ever match this one fabricated row -- that's what
    # lets these tests tell "filtered out" apart from "just didn't rank in the top 8".
    embedding = embed_passages([f"{section_number} test heading body text"])[0]
    conn.execute(
        """
        INSERT INTO sections (section_number, chapter, heading, text, source_url, allowed_groups, embedding)
        VALUES (%s, 999, %s, %s, %s, %s, %s)
        """,
        (
            section_number,
            "A confidential test heading",
            "A wholly fabricated confidential test section about zzyzxquorp irrigation.",
            "https://example.invalid/test",
            allowed_groups,
            embedding,
        ),
    )


def test_restricted_section_is_hidden_from_a_user_without_the_group(db_conn):
    _insert_restricted_section(db_conn, section_number="999.001", allowed_groups=["legal"])

    results = search(db_conn, TEST_QUESTION, user_groups=[])
    assert "999.001" not in {r.section_number for r in results}

    results = search(db_conn, TEST_QUESTION, user_groups=["engineering"])
    assert "999.001" not in {r.section_number for r in results}


def test_restricted_section_is_visible_to_a_user_with_the_group(db_conn):
    _insert_restricted_section(db_conn, section_number="999.002", allowed_groups=["legal"])

    results = search(db_conn, TEST_QUESTION, user_groups=["legal"])
    assert results[0].section_number == "999.002"


def test_public_section_is_visible_to_everyone(db_conn):
    _insert_restricted_section(db_conn, section_number="999.003", allowed_groups=[])

    results = search(db_conn, TEST_QUESTION, user_groups=[])
    assert results[0].section_number == "999.003"
