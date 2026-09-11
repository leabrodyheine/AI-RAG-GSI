"""Tests for orswater.answer.

Covers both answer backends:
- ``deterministic`` (the default -- must work with ANTHROPIC_API_KEY unset, must never
  construct or call an Anthropic client).
- ``anthropic`` (opt-in via ANSWER_BACKEND=anthropic) -- a fake Anthropic client stands
  in for the real SDK client so these run with no network access and no API key; they
  check that we build the search_result request blocks correctly and map the response's
  citations back to the right retrieved section, not that Claude's API behaves a
  particular way. No real Anthropic request is ever made by this file.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import orswater.answer as answer_module
from orswater.answer import MissingAnthropicCredentialsError, answer
from orswater.config import load_config
from orswater.search import Result

# ---------------------------------------------------------------------------
# Fakes standing in for the anthropic SDK client
# ---------------------------------------------------------------------------


@dataclass
class _FakeCitation:
    search_result_index: int
    cited_text: str
    type: str = "search_result_location"


@dataclass
class _FakeTextBlock:
    text: str
    citations: list | None = None
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


# ---------------------------------------------------------------------------
# ANSWER_BACKEND config: default, validation
# ---------------------------------------------------------------------------


def test_default_backend_is_deterministic_when_unset(monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    assert load_config().answer_backend == "deterministic"


def test_having_an_api_key_set_does_not_select_the_anthropic_backend(monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-some-real-looking-key")
    assert load_config().answer_backend == "deterministic"


def test_invalid_answer_backend_value_fails_clearly(monkeypatch):
    monkeypatch.setenv("ANSWER_BACKEND", "bogus")
    with pytest.raises(ValueError, match="ANSWER_BACKEND"):
        load_config()


@pytest.mark.parametrize(
    "key",
    [None, "", "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    ids=["missing", "empty", "documented-placeholder"],
)
def test_placeholder_and_empty_keys_are_not_real_credentials(monkeypatch, key):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    assert load_config().has_anthropic_credentials is False


# ---------------------------------------------------------------------------
# Deterministic backend (default): no API key, no Anthropic client
# ---------------------------------------------------------------------------


def test_deterministic_backend_never_constructs_an_anthropic_client(db_conn, monkeypatch):
    """Also the default-operation check: this must work with no ANTHROPIC_API_KEY at all."""
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _ExplodingAnthropic:
        def __init__(self, *args, **kwargs):
            raise AssertionError("deterministic backend must never construct anthropic.Anthropic")

    monkeypatch.setattr(answer_module.anthropic, "Anthropic", _ExplodingAnthropic)

    result = answer(db_conn, "What does ORS 537.545 say about exempt uses?", [])
    assert result.backend == "deterministic"


def test_deterministic_backend_cites_the_highest_ranked_section_verbatim(db_conn, monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)

    result = answer(db_conn, "What does ORS 537.545 say about exempt uses?", [])

    assert result.backend == "deterministic"
    top = result.retrieved_sections[0]
    assert top.section_number == "537.545"

    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.section_number == top.section_number
    assert citation.heading == top.heading
    # the excerpt must be verbatim -- a real substring of the actual retrieved text (an
    # ellipsis may be appended as a truncation marker when there's no nearby sentence
    # boundary to cut on, so strip that before checking)
    verbatim_part = citation.cited_text.rstrip("…")
    assert verbatim_part in top.text
    assert citation.cited_text in result.text


def test_deterministic_backend_labels_output_as_prototype_and_not_legal_advice(db_conn, monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)

    result = answer(db_conn, "What does ORS 537.545 say about exempt uses?", [])

    assert "deterministic prototype" in result.text.lower()
    assert "not an ai-generated interpretation" in result.text.lower()
    assert "not legal advice" in result.text.lower()


def test_no_results_response_is_preserved_regardless_of_backend(db_conn, monkeypatch):
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)
    db_conn.execute("DELETE FROM sections")  # rolled back by the db_conn fixture afterward

    result = answer(db_conn, "Can I dig a well?", [])

    assert result.text.startswith("No ORS sections")
    assert "not legal advice" in result.text.lower()
    assert result.citations == []
    assert result.retrieved_sections == []
    assert result.backend == "deterministic"


def _fake_result(*, section_number="999.001", distance):
    return Result(
        section_number=section_number,
        heading="A fabricated test heading",
        text="A fabricated test body long enough to be a plausible excerpt.",
        url="https://example.invalid/test",
        distance=distance,
    )


def test_deterministic_backend_reports_no_confident_match_for_a_weak_semantic_match():
    """Isolated from the DB and the real embedding model: a fabricated Result well past
    WEAK_MATCH_DISTANCE must not be quoted as if it answers the question."""
    weak = _fake_result(distance=answer_module.WEAK_MATCH_DISTANCE + 0.1)

    result = answer_module._deterministic_answer([weak])

    assert result.backend == "deterministic"
    assert result.citations == []
    assert result.retrieved_sections == [weak]  # still surfaced for transparency
    assert "no excerpt is being quoted" in result.text.lower()
    assert "not legal advice" in result.text.lower()


def test_deterministic_backend_quotes_a_strong_semantic_match():
    strong = _fake_result(distance=answer_module.WEAK_MATCH_DISTANCE - 0.1)

    result = answer_module._deterministic_answer([strong])

    assert len(result.citations) == 1
    assert result.citations[0].section_number == strong.section_number


def test_deterministic_backend_always_quotes_a_direct_citation_match_regardless_of_distance():
    # search() sets distance=None for a direct ORS-citation hit -- always treated as a
    # confident match, not run through the weak-match check at all.
    exact = _fake_result(distance=None)

    result = answer_module._deterministic_answer([exact])

    assert len(result.citations) == 1


def test_deterministic_backend_reports_no_confident_match_for_a_real_off_topic_question(
    db_conn, monkeypatch
):
    """End-to-end with the real embedding model and the real corpus: a question the ORS
    water-law chapters have nothing to do with should not come back quoting some
    unrelated section as if it were the answer."""
    monkeypatch.delenv("ANSWER_BACKEND", raising=False)

    result = answer(db_conn, "What is the speed limit on I-5?", [])

    assert result.backend == "deterministic"
    assert result.citations == []
    assert "no excerpt is being quoted" in result.text.lower()
    assert "not legal advice" in result.text.lower()
    assert len(result.retrieved_sections) >= 1  # still surfaced, just not cited as an answer


# ---------------------------------------------------------------------------
# Anthropic backend: opt-in only, injected fake client, missing-key error
# ---------------------------------------------------------------------------


def test_anthropic_backend_sends_one_search_result_block_per_retrieved_section_with_no_tools(
    db_conn, monkeypatch
):
    monkeypatch.setenv("ANSWER_BACKEND", "anthropic")

    response = _FakeResponse(content=[_FakeTextBlock(text="Yes, under ORS 537.545.")])
    client = _FakeClient(response)

    result = answer(db_conn, "What does ORS 537.545 say about exempt uses?", [], client=client)
    assert result.backend == "anthropic"

    assert len(client.messages.calls) == 1
    kwargs = client.messages.calls[0]

    assert "tools" not in kwargs  # Claude must get no tools

    blocks = kwargs["messages"][0]["content"]
    search_result_blocks = [b for b in blocks if b["type"] == "search_result"]
    assert len(search_result_blocks) == 1
    block = search_result_blocks[0]
    assert block["source"] == "https://www.oregonlegislature.gov/bills_laws/ors/ors537.html"
    assert block["title"].startswith("ORS 537.545")
    assert block["citations"] == {"enabled": True}
    assert len(block["content"]) == 1
    assert block["content"][0]["type"] == "text"
    assert "registration" in block["content"][0]["text"]  # real 537.545 body text

    # the question itself is the final content block
    assert blocks[-1] == {"type": "text", "text": "What does ORS 537.545 say about exempt uses?"}


def test_anthropic_backend_maps_citation_search_result_index_back_to_the_right_section(
    db_conn, monkeypatch
):
    monkeypatch.setenv("ANSWER_BACKEND", "anthropic")

    # Two fabricated, permission-public sections so we control exactly what's retrieved
    # and in what order, without depending on real ORS ranking.
    from orswater.embed import embed_passages

    for number, text in [
        ("999.101", "zzyzxquorp first fabricated test section."),
        ("999.102", "zzyzxquorp second fabricated test section."),
    ]:
        embedding = embed_passages([text])[0]
        db_conn.execute(
            """
            INSERT INTO sections (section_number, chapter, heading, text, source_url, allowed_groups, embedding)
            VALUES (%s, 999, %s, %s, %s, %s, %s)
            """,
            (number, "Test heading", text, "https://example.invalid/999", [], embedding),
        )

    response = _FakeResponse(
        content=[
            _FakeTextBlock(
                text="Answer citing the second result.",
                citations=[_FakeCitation(search_result_index=1, cited_text="the cited text")],
            )
        ]
    )
    client = _FakeClient(response)

    result = answer(db_conn, "zzyzxquorp", [], client=client)

    # Whichever section landed at position 1 among the search_result blocks is the one
    # search_result_index=1 must resolve to.
    expected_section = result.retrieved_sections[1]
    assert len(result.citations) == 1
    assert result.citations[0].section_number == expected_section.section_number
    assert result.citations[0].cited_text == "the cited text"


def test_anthropic_backend_skips_the_api_call_when_nothing_is_retrieved(db_conn, monkeypatch):
    monkeypatch.setenv("ANSWER_BACKEND", "anthropic")

    # search() always returns something once a section exists, since vector search ranks
    # by distance rather than a relevance threshold -- so the only way to exercise the
    # empty-retrieval branch is an empty table. Deleting here only affects this
    # connection's open transaction; the db_conn fixture rolls it back afterward, so the
    # real ingested corpus is untouched.
    db_conn.execute("DELETE FROM sections")

    client = _FakeClient(_FakeResponse(content=[]))
    result = answer(db_conn, "Can I dig a well?", [], client=client)

    assert result.text.startswith("No ORS sections")
    assert result.citations == []
    assert result.retrieved_sections == []
    assert client.messages.calls == []  # no API call made when there's nothing to answer from


def test_anthropic_backend_without_a_real_key_fails_before_any_network_request(db_conn, monkeypatch):
    monkeypatch.setenv("ANSWER_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # missing

    with pytest.raises(MissingAnthropicCredentialsError, match="ANTHROPIC_API_KEY"):
        answer(db_conn, "What does ORS 537.545 say about exempt uses?", [])  # no client injected


def test_anthropic_backend_treats_the_documented_placeholder_key_as_missing(db_conn, monkeypatch):
    monkeypatch.setenv("ANSWER_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")

    with pytest.raises(MissingAnthropicCredentialsError):
        answer(db_conn, "What does ORS 537.545 say about exempt uses?", [])
