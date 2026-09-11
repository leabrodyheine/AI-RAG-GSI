"""``answer(conn, question, user_groups)`` -- retrieves via search() and produces an
answer, using one of two backends selected by the ``ANSWER_BACKEND`` env var:

- ``deterministic`` (the default): no model, no API call, no network access at all --
  just a bounded verbatim excerpt of the highest-ranked retrieved section. This is what
  lets the whole prototype (ingest, search, evaluate, answer) run end to end with no
  Anthropic API key.
- ``anthropic``: sends the retrieved sections to Claude as ``search_result`` content
  blocks with citations enabled (the SDK's citations feature, verified against the
  installed anthropic SDK -- no beta header, no tool). Claude is given no tools: it
  cannot browse the web or write files, only answer from the sections it was handed.
  Only opted into explicitly -- ANTHROPIC_API_KEY existing is never enough by itself.

Document text only ever goes to Claude when the anthropic backend is explicitly selected;
the deterministic backend never sends anything anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import anthropic
import psycopg

from .config import Config, load_config
from .search import Result, search

SYSTEM_PROMPT = """You answer questions about Oregon water law using ONLY the ORS (Oregon \
Revised Statutes) sections provided to you as search results in this conversation.

Rules:
- Base your answer only on the provided sections. Never use outside knowledge of Oregon \
water law, even if you believe it to be correct.
- If the provided sections do not address the question, say so plainly instead of \
guessing -- do not imply an answer the text doesn't support.
- Cite the specific ORS section number(s) you relied on.
- You are not a lawyer and this is general information, not legal advice. Say so when you \
give a substantive answer.
"""

LEGAL_DISCLAIMER = "This is general information, not legal advice."

NO_RESULTS_TEXT = (
    "No ORS sections in chapters 536-540 were found that this user has access to and "
    f"that relate to this question. {LEGAL_DISCLAIMER}"
)

# A bounded, verbatim excerpt -- long enough to be useful, short enough to stay a
# "prototype result" rather than dumping the whole section. Real ORS text often runs
# semicolon-joined subsections with no period for a long stretch (e.g. 537.545's first
# sentence is 1600+ characters), so a sentence boundary near the cap isn't guaranteed;
# EXCERPT_EXTENSION_FACTOR lets the excerpt run a little long to catch a nearby one
# before giving up and hard-cutting with an ellipsis.
EXCERPT_MAX_CHARS = 700
EXCERPT_EXTENSION_FACTOR = 1.3
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


class MissingAnthropicCredentialsError(RuntimeError):
    """ANSWER_BACKEND=anthropic was selected but no usable ANTHROPIC_API_KEY is set."""


@dataclass(frozen=True)
class Citation:
    section_number: str
    heading: str
    cited_text: str


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation]
    retrieved_sections: list[Result]
    backend: str


def _bounded_excerpt(text: str, max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """A verbatim prefix of ``text``, capped near ``max_chars``. Ends at the last sentence
    boundary at or before the cap when there is one; otherwise looks a little further for
    the next boundary; otherwise hard-cuts and marks the excerpt as truncated."""
    if len(text) <= max_chars:
        return text

    search_limit = int(max_chars * EXCERPT_EXTENSION_FACTOR)
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(text[:search_limit])]
    within_cap = [e for e in ends if e <= max_chars]
    if within_cap:
        return text[: within_cap[-1]]
    if ends:
        return text[: ends[0]]
    return text[:max_chars].rstrip() + "…"


def _deterministic_answer(retrieved: list[Result]) -> Answer:
    """No model, no API, no network call -- a bounded verbatim excerpt of the
    highest-ranked retrieved section, clearly labeled as a prototype retrieval result
    rather than an AI-generated interpretation."""
    top = retrieved[0]
    excerpt = _bounded_excerpt(top.text)
    text = (
        "[Deterministic prototype result -- a verbatim excerpt of the retrieved text, "
        "not an AI-generated interpretation]\n\n"
        f"ORS {top.section_number} — {top.heading}\n\n"
        f"{excerpt}\n\n"
        f"{LEGAL_DISCLAIMER}"
    )
    citation = Citation(
        section_number=top.section_number,
        heading=top.heading,
        cited_text=excerpt,
    )
    return Answer(
        text=text,
        citations=[citation],
        retrieved_sections=retrieved,
        backend="deterministic",
    )


def _to_search_result_block(result: Result) -> dict:
    return {
        "type": "search_result",
        "source": result.url,
        "title": f"ORS {result.section_number} — {result.heading}",
        "content": [{"type": "text", "text": result.text}],
        "citations": {"enabled": True},
    }


def _anthropic_answer(
    retrieved: list[Result],
    question: str,
    config: Config,
    *,
    client: anthropic.Anthropic | None,
) -> Answer:
    if client is None:
        # Only check credentials on the path that would otherwise make a real request --
        # an injected test client is exempt, same as before.
        if not config.has_anthropic_credentials:
            raise MissingAnthropicCredentialsError(
                "ANSWER_BACKEND=anthropic requires a real ANTHROPIC_API_KEY. An empty "
                "value or the .env.example placeholder doesn't count. Set a real key in "
                ".env, or unset ANSWER_BACKEND (or set it to 'deterministic') to use the "
                "no-API-key prototype backend instead."
            )
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    content = [_to_search_result_block(r) for r in retrieved]
    content.append({"type": "text", "text": question})

    response = client.messages.create(
        model=config.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    text_parts: list[str] = []
    citations: list[Citation] = []
    for block in response.content:
        if block.type != "text":
            continue
        text_parts.append(block.text)
        for c in block.citations or []:
            if c.type != "search_result_location":
                continue
            # search_result_index is 0-based among search_result blocks in the order they
            # appear -- that's exactly the order `retrieved` was turned into blocks above.
            section = retrieved[c.search_result_index]
            citations.append(
                Citation(
                    section_number=section.section_number,
                    heading=section.heading,
                    cited_text=c.cited_text,
                )
            )

    return Answer(
        text="".join(text_parts),
        citations=citations,
        retrieved_sections=retrieved,
        backend="anthropic",
    )


def answer(
    conn: psycopg.Connection,
    question: str,
    user_groups: list[str],
    *,
    client: anthropic.Anthropic | None = None,
) -> Answer:
    """Retrieve relevant sections and answer from them using the configured backend.

    Backend is chosen by the ``ANSWER_BACKEND`` env var (``deterministic`` by default;
    ``anthropic`` must be set explicitly -- having ANTHROPIC_API_KEY set is never enough
    by itself). ``client`` can be injected for testing the anthropic backend; otherwise
    one is built from ANTHROPIC_API_KEY when that backend is selected.
    """
    config = load_config()
    retrieved = search(conn, question, user_groups)

    if not retrieved:
        return Answer(
            text=NO_RESULTS_TEXT,
            citations=[],
            retrieved_sections=[],
            backend=config.answer_backend,
        )

    if config.answer_backend == "deterministic":
        return _deterministic_answer(retrieved)
    return _anthropic_answer(retrieved, question, config, client=client)
