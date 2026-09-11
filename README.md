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
- The answer step has three backends, chosen by `ANSWER_BACKEND` (default `deterministic`): `deterministic` needs no API key, model, or network call at all (a bounded verbatim excerpt of the top retrieved section); `ollama` sends retrieved sections to a local open-weight model over the Ollama REST API (free, but requires Ollama installed and running); `anthropic` is opted into explicitly and sends retrieved sections to Claude for a paid, more reliable cited answer. Having `ANTHROPIC_API_KEY` set never selects `anthropic` by itself, and `ollama`/`anthropic` are both explicit opt-ins over the zero-dependency `deterministic` default.

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
`orswater ask "..."` (answer a question), and the web page:

```bash
# One-time: build the React frontend (needs Node.js; static output only, no Node at runtime)
cd web && npm install && npm run build && cd ..

# Serve the API + built frontend together
uvicorn orswater.web:app --port 8000       # open http://localhost:8000
```

For frontend development instead of a rebuild-per-change loop, run `npm run dev` in `web/`
(Vite dev server on :5173, proxying `/api` to `uvicorn orswater.web:app --port 8000` running
separately) rather than the build step above.

### Do I need an API key?

No, not for most of this prototype. Ingestion, embeddings, retrieval (`search()`),
retrieval evaluation (`scripts/eval_retrieval.py`), and the default `deterministic`
answer backend all run entirely locally against Postgres — no `ANTHROPIC_API_KEY`
required, no network call at answer time. Embeddings use `BAAI/bge-small-en-v1.5` via
sentence-transformers, which also runs locally; its weights (~130 MB) are downloaded
from Hugging Face the first time it's used and cached afterward, so the very first
ingest or search does need network access for that one-time download, not for anything
document-related.

Set `ANSWER_BACKEND=ollama` in `.env` for a free natural-language cited answer from a
local model instead of the deterministic backend's verbatim excerpt -- requires
[Ollama](https://ollama.com/download) installed and running (`ollama serve`) with the
configured model pulled (`ollama pull llama3.2:3b`, the default `OLLAMA_MODEL`). No API
key, no cost, but slower than Claude and less reliable at following the citation
instructions (its citations come from scanning its answer text for section numbers and
keeping only ones that were actually retrieved, not a structured citation API).

Set `ANSWER_BACKEND=anthropic` in `.env` if you want natural-language cited answers from
Claude instead. That's opt-in, requires a real `ANTHROPIC_API_KEY` (from
[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)), and
incurs Anthropic API usage costs.

### Layout

| Path | Purpose |
| --- | --- |
| `sql/schema.sql` | the single `sections` table + HNSW and GIN indexes |
| `docker-compose.yml` | Postgres 17 with the pgvector extension |
| `src/orswater/config.py` | env config (`ANSWER_BACKEND`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `DATABASE_URL`) |
| `src/orswater/db.py` | psycopg connection + schema setup |
| `src/orswater/fetch.py` / `parse.py` / `embed.py` / `ingest.py` | ingestion pipeline (M2) |
| `src/orswater/search.py` | `search(question, user_groups)` — the swappable retrieval seam (M3); each result also carries the embedding distance used by the deterministic backend's relevance threshold |
| `src/orswater/answer.py` | `answer()` — deterministic (default, no API key), local-Ollama, or Claude-with-citations backend, chosen by `ANSWER_BACKEND` (M5) |
| `src/orswater/web.py` | FastAPI JSON API (`POST /api/ask`), serves the built frontend as static files (M6) |
| `web/` | React + TypeScript frontend (Vite), built separately -- `web/src/App.tsx` (markup/logic), `web/src/App.css` (styles), `web/src/api.ts` + `web/src/types.ts` (typed API client) (M6) |
| `evals/` | retrieval evaluation set + report script (M4) |
| `tests/` | parser and search unit tests |

Nothing document-derived leaves the machine except the section text sent to Claude at
answer time; embeddings are computed locally and no tracing/telemetry services are used.

## Final summary (Milestone 6)

**What was built.** A FastAPI JSON API (`src/orswater/web.py`, one route:
`POST /api/ask`) in front of the same `answer()` used by the CLI, so the web page and
`orswater ask` share identical retrieval, permission filtering, and backend selection.
The frontend is a separate React + TypeScript project (`web/`, built with Vite): a
question box, the answer text with the backend that produced it labeled (`backend-badge`),
a clickable "Cited sections" list (links to the ORS chapter page, quoting the exact cited
text), a "Retrieved sections" list (the full "find documents" set, each linking to its
source page), and a persistent "general information, not legal advice" notice. HTML
(`web/index.html`), CSS (`web/src/App.css`), and TS/TSX (`web/src/*.tsx`/`.ts`) are kept in
separate files, per instruction, rather than one static page. `web/dist` (the build output)
is what `web.py` serves as static files; it's gitignored, same as `web/node_modules`.

**Key decisions.**

- One API route, matching the README's scope ("a FastAPI endpoint plus one static HTML
  page") -- no auth, sessions, or extra endpoints not asked for.
- `Citation` objects don't carry a URL (the CLI has no use for one), so `web.py` joins
  each citation to its `retrieved_sections` entry by `section_number` to attach one for
  "clickable citations," rather than changing the shared `answer.py` data model.
- The React dev server proxies `/api` to the FastAPI app (`web/vite.config.ts`) instead of
  adding CORS middleware -- one fewer moving part for a same-origin production setup.
- `ANSWER_BACKEND=anthropic` without a real key returns HTTP 503 with the same
  `MissingAnthropicCredentialsError` message the CLI prints, rather than a 200 with an
  error string in the answer body.

**Checks actually run:**

- `pytest`: **42/42 passed** (4 new in `tests/test_web.py`, covering a real deterministic
  answer through the live API with citation URL, an empty-corpus 200 with the no-results
  text -- via the shared test DB connection, never committed, so the real 412-row corpus
  was untouched and reconfirmed by count afterward -- and a 503 with no Anthropic key).
- `ruff check .`: **all checks passed**.
- `python -m py_compile` on `src/orswater/web.py` and `tests/test_web.py`: clean.
- Frontend: `cd web && npm install && npm run build` -- `tsc --noEmit` (strict mode) and
  the Vite production build both **succeeded** (144.79 kB JS / 1.63 kB CSS, gzipped
  46.67 kB / 0.70 kB).
- Live, end-to-end, by hand: started `uvicorn orswater.web:app --port 8000`, confirmed
  `GET /` serves the built React `index.html`, then `POST /api/ask` for both a real
  question (ORS 537.545, deterministic backend, citation URL correct) and one the
  statutes don't answer well (returns the closest retrieved sections rather than
  fabricating an answer). No live Anthropic request was made -- `ANSWER_BACKEND` stayed at
  its `deterministic` default throughout.

**Limitations.**

- No automated browser/UI test (no headless-browser tooling in this environment) -- the
  frontend was verified by a real `npm run build` plus manual `curl` calls against the
  running API, not by rendering it in an actual browser.
- `npm audit` flags a moderate advisory in Vite's dev-only `esbuild` dependency (a
  malicious site could probe the local Vite **dev server**, not the production build or
  the FastAPI app); left as-is rather than force-upgrading Vite to a breaking major
  version for a prototype.
- The React app has no build step wired into CI/tests -- `npm run build` must be run
  manually before `uvicorn orswater.web:app` has anything to serve at `/`; without it, `/`
  returns a plain instruction message instead of failing.
- Inline citation highlighting within the answer text itself wasn't built; citations are
  shown as a separate list under the answer rather than as inline markers, which keeps the
  UI simple but doesn't visually tie a specific sentence in the answer to its source.

## Follow-up: Ollama backend, relevance threshold, disclaimer UI (post-M6)

Three changes made after the initial six milestones, in response to feedback on the
running prototype.

**1. Added the `ollama` answer backend.** The original spec called for a free local-model
backend as the two the answer step supports; only `deterministic` (no model at all) and
`anthropic` had been built. `ollama` now fills that gap: retrieved sections are formatted
into a numbered list in the prompt (no structured citation mechanism like Claude's
`search_result` blocks exists for it), sent to a local Ollama server over its REST API
(`POST /api/chat`, no SDK, no beta header -- confirmed against the current Ollama docs),
and citations are recovered by scanning the model's answer text for ORS section numbers
and keeping only ones that were actually retrieved (`_extract_cited_sections` in
`answer.py`) -- a number the model invents, or one outside the retrieved set, is dropped
rather than shown as a real source. Default model is `llama3.2:3b` (~2GB, runs on CPU,
reliable enough at following the system prompt's citation instructions for a prototype;
see `config.py` for the tradeoff note against the larger, paid, more reliable Claude
backend). Selecting `ANSWER_BACKEND=ollama` with no reachable server fails clearly with
install/run instructions (`OllamaUnavailableError`), both from the CLI and as an HTTP 503
from the web API, rather than hanging or failing mid-question.

**2. Added a relevance threshold to the deterministic backend.** Previously the
deterministic backend always quoted the single top-ranked retrieved section, even for
questions entirely unrelated to Oregon water law (e.g. "What is the speed limit on I-5?"),
since vector search ranks by distance rather than applying a cutoff -- there being no LLM
in that backend to judge whether the retrieved text actually answers the question. Fixed
by threading each result's cosine distance from `search()` (`Result.distance`, `None` for
a direct ORS-citation match, which is exact by construction) into a calibrated
`WEAK_MATCH_DISTANCE = 0.40` cutoff in `answer.py`: above it, the response says plainly
that nothing retrieved looks like a close match instead of quoting the nearest section as
if it were the answer. The cutoff was calibrated against the real distances of all 25
`evals/questions.jsonl` questions (max: 0.328) and several deliberately off-topic
questions (0.40–0.59), leaving margin on both sides; it won't catch every off-topic or
domain-adjacent question, and this doesn't apply to the `ollama`/`anthropic` backends,
which judge relevance with an actual model instead. `search()`'s own retrieval/ranking is
unchanged by this -- confirmed by re-running `scripts/eval_retrieval.py` (still 22/25,
88%, identical misses).

**3. Hid the "not legal advice" disclaimer in the web UI only.** The backend text
(`answer.py`'s `LEGAL_DISCLAIMER`), the CLI output, and this README's requirement for one
are all unchanged -- a real deployment still needs it, and the spec explicitly calls for
"a visible 'not legal advice' note." The React app now strips that exact string from what
it displays (`web/src/App.tsx`'s `withoutDisclaimer`), a UI-only presentation choice for
this prototype rather than a backend change.

**Checks actually run for this round:**

- `pytest`: **59/59 passed** (12 new: 2 config tests for the `ollama` backend value and
  its `OLLAMA_HOST`/`OLLAMA_MODEL` defaults, 7 covering the ollama backend end-to-end via
  `httpx.MockTransport` -- request shape, no tools, invented-citation filtering, dedup,
  unreachable-server and model-not-pulled errors, skipping the HTTP call on empty
  retrieval -- 3 pure unit tests of `_extract_cited_sections`, plus the relevance-threshold
  tests from the prior round).
- `ruff check .`: **all checks passed**.
- `scripts/eval_retrieval.py`: **22/25, 88%**, unchanged from before the `Result.distance`
  refactor (confirms retrieval itself wasn't altered, only what the deterministic backend
  says about a weak match).
- `cd web && npm run build`: `tsc --noEmit` and the Vite production build both
  **succeeded**.
- Live, end-to-end, by hand: `POST /api/ask` for "What is the speed limit on I-5?" now
  returns the no-confident-match text with no citation (previously quoted an unrelated
  section); `POST /api/ask` for an on-topic question (governor's drought-declaration
  authority) still cites `ORS 536.740` normally. `ANSWER_BACKEND=ollama` with no local
  Ollama server installed fails with the documented clear error via both `orswater ask`
  and `POST /api/ask` (curled directly, confirmed HTTP 503 with that message) -- no live
  Ollama request was made anywhere in this round, since Ollama isn't installed on this
  machine.

**Limitations added this round:**

- The `ollama` backend has never actually been run against a real Ollama server on this
  machine (Ollama isn't installed here) -- it's verified via `httpx.MockTransport` (real
  request/response shapes, no network) and a real connection-refused error path, not a
  real end-to-end generation. Anyone using it should expect to debug real-model quirks
  (formatting, occasionally ignoring the "say so when the sections don't answer" rule)
  that a mocked test can't catch.
- `WEAK_MATCH_DISTANCE` is a single global cutoff tuned against this specific corpus and
  embedding model; it would need recalibrating against real distances if the corpus,
  embedding model, or domain changes.
