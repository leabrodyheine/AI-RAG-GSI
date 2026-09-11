# Build: Oregon water law RAG prototype

## Goal

Build a small, working RAG prototype that answers questions about Oregon water law using the Oregon Revised Statutes (ORS), with Claude as the LLM. Answers must cite the specific ORS sections they rely on. The prototype proves out an architecture that will later run over a company's private documents (likely Microsoft 365 or a Windows file server), so keep retrieval behind one function that can be swapped out later.

## Working rules

- Before writing code, read the current official docs for anything you use: pgvector, Postgres full-text search, sentence-transformers, FastAPI, and the Anthropic Python SDK (especially search result content blocks and citations at docs.claude.com). Do not guess API shapes.
- Prefer the simplest correct solution. No LangChain, LlamaIndex, ORMs, rerankers, or other frameworks. Plain Python, SQL, and direct SDK calls.
- Don't build for hypothetical requirements. Only what's listed here.
- Git: I must be the only author. Never add Co-authored-by, Generated-by, or any AI attribution. Make small, focused commits with accurate messages that include checks actually run (e.g. "12/12 tests passed"). Never claim a check passed unless you ran it.
- Never commit `.env`, API keys, cached HTML, model weights, or other generated files. Add a `.gitignore` early.
- Report failures honestly. Never weaken or skip tests to make them pass.
- After each milestone below: commit, summarize what changed and what checks you ran, then STOP and wait for my go-ahead.

## Design

**Data:** ORS chapters 536, 537, 538, 539, and 540 (core water rights law), one HTML page per chapter at `https://www.oregonlegislature.gov/bills_laws/ors/ors537.html` (same pattern for each chapter). Verify these URLs load before relying on them.

**Stack:** Python 3.11+, Postgres with the pgvector extension (run via Docker Compose using the official pgvector image), a small local open-source English embedding model via sentence-transformers (check the docs and choose a well-supported small model, e.g. BAAI/bge-small-en-v1.5; justify the choice), the Anthropic Python SDK, and FastAPI serving one static HTML page.

**Security constraints (these mirror the production requirements):**

- Document text may only go to Claude. Embeddings are computed locally. No third-party telemetry, tracing, or logging services.
- Don't log full prompts or retrieved text by default.
- Claude gets no tools: no web access, no file writes. Read-only question answering.
- API key comes from the `ANTHROPIC_API_KEY` env var; model from `ANTHROPIC_MODEL`, defaulting to `claude-sonnet-5`. Provide `.env.example`.
- The answer step has two backends, chosen by `ANSWER_BACKEND` (default `deterministic`): `deterministic` needs no API key and makes no external call at all (a bounded verbatim excerpt of the top retrieved section); `anthropic` is opted into explicitly and sends retrieved sections to Claude. Having `ANTHROPIC_API_KEY` set never selects `anthropic` by itself.

**Schema:** one `sections` table with section_number (unique, e.g. "537.130"), chapter, heading, text, source_url, edition (read from the page), allowed_groups (text array, empty = public), embedding (vector), and a generated tsvector column. Add an HNSW index on the embedding and a GIN index on the tsvector.

**Retrieval:** a single function, `search(question, user_groups) -> list of results`, with each result carrying section number, heading, text, and URL.

1. If the question contains an ORS citation (e.g. "537.545"), return that section first.
2. Otherwise run full-text search and vector search (top 20 each), merge with reciprocal rank fusion (k=60), and return the top 8.
3. Permission filtering happens inside the SQL query: a row is visible if allowed_groups is empty or overlaps user_groups. Never filter after retrieval or via the prompt.

**Answering:** send the retrieved sections to Claude as search result content blocks with citations enabled (confirm the exact format in the docs). The system prompt says: answer only from the provided sections; say plainly when they don't answer the question; cite section numbers; this is general information, not legal advice. Return the answer, its citations, and the full list of retrieved sections (the "find documents" feature).

## Milestones

**0. Plan.** Read the docs listed above. Fetch one chapter page and inspect its real HTML structure (section numbers, headings, repealed or renumbered sections, edition marker). Propose a short plan and file layout. Stop.

**1. Scaffold.** pyproject.toml, docker-compose.yml, schema creation, `.gitignore`, `.env.example`, and a README with setup steps. Verify Postgres starts and the schema applies. Stop.

**2. Ingest.** A script that fetches the five chapters (caching raw HTML in a gitignored folder), parses one row per section, embeds, and upserts. Decide how to handle repealed and renumbered sections and explain the choice. Add parser unit tests using small saved HTML fixtures. Print section counts per chapter and three sample parsed sections. Stop so I can eyeball the chunks.

**3. Search.** Implement `search()` as designed. Add tests for citation detection, RRF merging, and permission filtering (insert a test row with allowed_groups set and confirm it is hidden from other users). Stop.

**4. Evaluate retrieval.** Create `evals/questions.jsonl` with 25 questions. Write each question by reading a specific section first, phrase it the way a non-lawyer would ask (don't copy the section heading), and record the expected section number(s). Write a script that reports how often an expected section appears in the top 8, and lists the misses. Run it and report the real numbers. Stop, because I will review the questions for accuracy.

**5. Answer.** Implement the Claude call and a CLI command: `ask "question"`. Show two example runs, including one question the statutes don't answer. Stop.

**6. Web page.** A FastAPI endpoint plus one static HTML page: question box, answer with clickable citations, the retrieved sections list with links to the source pages, and a visible "not legal advice" note. Stop and give a final summary covering what was built, key decisions, all checks run with results, and known limitations.

---

## Setup (prototype)

Requires Python 3.11+ and Docker.

```bash
# 1. Config
cp .env.example .env          # defaults to ANSWER_BACKEND=deterministic -- no API key needed

# 2. Postgres + pgvector
docker compose up -d          # starts Postgres on localhost:5432

# 3. Python environment
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 4. Create the schema
python -m orswater.db         # applies sql/schema.sql, prints the pgvector version
```

Later milestones add: `python -m orswater.ingest` (fetch + parse + embed the ORS chapters),
`orswater ask "..."` (answer a question), and `uvicorn orswater.web:app` (the web page).

### Do I need an API key?

No, not for most of this prototype. Ingestion, embeddings, retrieval (`search()`),
retrieval evaluation (`scripts/eval_retrieval.py`), and the default `deterministic`
answer backend all run entirely locally against Postgres — no `ANTHROPIC_API_KEY`
required, no network call at answer time. Embeddings use `BAAI/bge-small-en-v1.5` via
sentence-transformers, which also runs locally; its weights (~130 MB) are downloaded
from Hugging Face the first time it's used and cached afterward, so the very first
ingest or search does need network access for that one-time download, not for anything
document-related.

Set `ANSWER_BACKEND=anthropic` in `.env` only if you want natural-language cited answers
from Claude instead of the deterministic backend's verbatim excerpt. That's opt-in,
requires a real `ANTHROPIC_API_KEY` (from
[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)), and
incurs Anthropic API usage costs.

### Layout

| Path | Purpose |
| --- | --- |
| `sql/schema.sql` | the single `sections` table + HNSW and GIN indexes |
| `docker-compose.yml` | Postgres 17 with the pgvector extension |
| `src/orswater/config.py` | env config (`ANSWER_BACKEND`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `DATABASE_URL`) |
| `src/orswater/db.py` | psycopg connection + schema setup |
| `src/orswater/fetch.py` / `parse.py` / `embed.py` / `ingest.py` | ingestion pipeline (M2) |
| `src/orswater/search.py` | `search(question, user_groups)` — the swappable retrieval seam (M3) |
| `src/orswater/answer.py` | `answer()` — deterministic (default, no API key) or Claude-with-citations backend, chosen by `ANSWER_BACKEND` (M5) |
| `src/orswater/web.py` + `web/index.html` | FastAPI page (M6) |
| `evals/` | retrieval evaluation set + report script (M4) |
| `tests/` | parser and search unit tests |

Nothing document-derived leaves the machine except the section text sent to Claude at
answer time; embeddings are computed locally and no tracing/telemetry services are used.
