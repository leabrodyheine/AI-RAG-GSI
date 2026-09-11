"""``answer(conn, question, user_groups)`` -- retrieves via search() and produces an
answer, using one of three backends selected by the ``ANSWER_BACKEND`` env var:

- ``deterministic`` (the default): no model, no API call, no network access at all --
  just a bounded verbatim excerpt of the highest-ranked retrieved section. This is what
  lets the whole prototype (ingest, search, evaluate, answer) run end to end with no
  Anthropic API key and no local model, and is a superset of what the original spec's
  free/dev-mode backend needed (it never sends anything anywhere at all).
- ``ollama``: a local open-weight model via the Ollama REST API (no SDK -- direct HTTP,
  per the Ollama docs). Free, local, but slower and less reliable than Claude, and has no
  structured citation mechanism: the retrieved sections are formatted into the prompt as a
  numbered list, and citations are recovered afterward by scanning the model's answer text
  for ORS section numbers and keeping only the ones that were actually retrieved (a number
  the model invented, or one outside the retrieved set, is dropped rather than shown as a
  source -- see _extract_cited_sections).
- ``anthropic``: sends the retrieved sections to Claude as ``search_result`` content
  blocks with citations enabled (the SDK's citations feature, verified against the
  installed anthropic SDK -- no beta header, no tool). Claude is given no tools: it
  cannot browse the web or write files, only answer from the sections it was handed.
  Only opted into explicitly -- ANTHROPIC_API_KEY existing is never enough by itself.

Document text goes to Ollama (a local process) when that backend is selected, and to
Claude only when the anthropic backend is explicitly selected; the deterministic backend
never sends anything anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import anthropic
import httpx
import psycopg

from .config import Config, load_config
from .search import CITATION_RE, Result, search

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

# Cosine distance above which the top retrieved section is considered too weak a semantic
# match to quote as if it answers the question -- there's no LLM in the deterministic
# backend to judge relevance, so this is the only signal it has. Calibrated against the 25
# real evals/questions.jsonl questions (max distance among their real top-1 matches:
# 0.328) and a handful of clearly off-topic questions ("What is the speed limit on I-5?":
# 0.455; "What's a good recipe for banana bread?": 0.588), leaving margin on both sides.
# It won't catch every off-topic question (a domain-adjacent one can still score low), and
# doesn't apply to a direct ORS-citation match (Result.distance is None there -- an exact
# citation is inherently a confident match).
WEAK_MATCH_DISTANCE = 0.40

# Local generation on CPU can be slow, especially the first call after the model is
# loaded into memory -- long enough to be generous, short enough to fail rather than hang
# forever if the server is stuck.
OLLAMA_TIMEOUT_SECONDS = 120.0


class MissingAnthropicCredentialsError(RuntimeError):
    """ANSWER_BACKEND=anthropic was selected but no usable ANTHROPIC_API_KEY is set."""


class OllamaUnavailableError(RuntimeError):
    """ANSWER_BACKEND=ollama was selected but the Ollama server isn't reachable, or
    rejected the request (e.g. the configured model hasn't been pulled)."""


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
    rather than an AI-generated interpretation.

    The only relevance signal available without an LLM is the top result's embedding
    distance (search.py always attaches one except for a direct ORS-citation match, which
    is exact by construction). When that distance is weak, quoting the section as if it
    answers the question would be misleading, so this says plainly that nothing retrieved
    looks like a close match instead -- see WEAK_MATCH_DISTANCE for how that cutoff was
    chosen."""
    top = retrieved[0]

    if top.distance is not None and top.distance > WEAK_MATCH_DISTANCE:
        text = (
            "[Deterministic prototype result]\n\n"
            "None of the retrieved ORS sections look like a close match for this "
            f"question (closest: ORS {top.section_number} — {top.heading}), so no excerpt "
            "is being quoted as an answer. See the retrieved sections list in case one is "
            f"still useful.\n\n{LEGAL_DISCLAIMER}"
        )
        return Answer(text=text, citations=[], retrieved_sections=retrieved, backend="deterministic")

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


def _format_ollama_sections(retrieved: list[Result]) -> str:
    """A numbered list of section number, heading, and full text -- what the model sees.
    Unlike the anthropic backend's search_result blocks, Ollama has no structured citation
    mechanism, so the section numbers are spelled out directly in the prompt text and
    recovered afterward by scanning the model's answer (_extract_cited_sections)."""
    return "\n\n".join(
        f"{i}. ORS {r.section_number} — {r.heading}\n{r.text}" for i, r in enumerate(retrieved, start=1)
    )


def _extract_cited_sections(text: str, retrieved: list[Result]) -> list[Citation]:
    """Scan a free-text model answer for ORS section numbers and keep only the ones that
    were actually retrieved, in first-mention order with duplicates dropped. This is
    Ollama's only citation mechanism (no structured citation data like the anthropic
    backend gets) -- a number the model invented, or one outside the retrieved set, is
    dropped rather than shown as if it were a real source."""
    retrieved_by_number = {r.section_number: r for r in retrieved}
    seen: set[str] = set()
    citations: list[Citation] = []
    for match in CITATION_RE.finditer(text):
        section_number = f"{match.group(1)}.{match.group(2)}"
        if section_number in seen or section_number not in retrieved_by_number:
            continue
        seen.add(section_number)
        section = retrieved_by_number[section_number]
        citations.append(
            Citation(
                section_number=section.section_number,
                heading=section.heading,
                cited_text=_bounded_excerpt(section.text),
            )
        )
    return citations


def _ollama_answer(
    retrieved: list[Result],
    question: str,
    config: Config,
    *,
    http_client: httpx.Client | None = None,
) -> Answer:
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=OLLAMA_TIMEOUT_SECONDS)
    user_content = f"{_format_ollama_sections(retrieved)}\n\nQuestion: {question}"

    try:
        response = client.post(
            f"{config.ollama_host}/api/chat",
            json={
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
    except httpx.ConnectError as e:
        raise OllamaUnavailableError(
            f"ANSWER_BACKEND=ollama requires a running Ollama server at {config.ollama_host}, "
            "but it isn't reachable. Install it (https://ollama.com/download), start it "
            f"(`ollama serve`), and pull the configured model (`ollama pull "
            f"{config.ollama_model}`) -- or unset ANSWER_BACKEND (or set it to "
            "'deterministic') to use the no-dependency prototype backend instead."
        ) from e
    except httpx.HTTPStatusError as e:
        raise OllamaUnavailableError(
            f"Ollama at {config.ollama_host} rejected the request ({e.response.status_code}): "
            f"{e.response.text.strip()}. If {config.ollama_model!r} hasn't been pulled yet, "
            f"run `ollama pull {config.ollama_model}`."
        ) from e
    finally:
        if owns_client:
            client.close()

    text = response.json()["message"]["content"]
    citations = _extract_cited_sections(text, retrieved)
    return Answer(text=text, citations=citations, retrieved_sections=retrieved, backend="ollama")


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
    ollama_client: httpx.Client | None = None,
) -> Answer:
    """Retrieve relevant sections and answer from them using the configured backend.

    Backend is chosen by the ``ANSWER_BACKEND`` env var (``deterministic`` by default;
    ``ollama`` and ``anthropic`` must be set explicitly -- having ANTHROPIC_API_KEY set is
    never enough by itself). ``client`` can be injected for testing the anthropic backend
    and ``ollama_client`` for testing the ollama backend (an httpx.Client, e.g. built with
    a MockTransport); otherwise real ones are built from config when those backends are
    selected.
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
    if config.answer_backend == "ollama":
        return _ollama_answer(retrieved, question, config, http_client=ollama_client)
    return _anthropic_answer(retrieved, question, config, client=client)
