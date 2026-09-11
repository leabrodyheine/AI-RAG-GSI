# Build: Oregon water law RAG prototype

## Goal

Build a small, working RAG prototype that answers questions about Oregon water law using the Oregon Revised Statutes (ORS). Answers must cite the specific ORS sections they rely on. The prototype proves out an architecture that will later run over a company's private documents on an on-premises Windows file server, so keep retrieval behind one function that can be swapped out later.

The answer step supports two interchangeable backends, selected by an env var:

- **`ollama`** — a local open-weight model, free to run. Use this for development.
- **`anthropic`** — Claude via the Anthropic API, paid per token, with native citations. This is the production-candidate backend.

Everything except the answer step is identical between the two, and milestones 0–4 need neither.

## Working rules

- Before writing code, read the current official docs for anything you use: pgvector, Postgres full-text search, sentence-transformers, FastAPI, the Ollama REST API, and the Anthropic Python SDK (especially search result content blocks and citations at docs.claude.com). Do not guess API shapes.
- Prefer the simplest correct solution. No LangChain, LlamaIndex, ORMs, rerankers, or other frameworks. Plain Python, SQL, and direct HTTP or SDK calls.
- Don't build for hypothetical requirements. Only what's listed here. In particular, the two answer backends are two functions plus a small dispatch, not a plugin system, class hierarchy, or registry.
- Git: I must be the only author. Never add Co-authored-by, Generated-by, or any AI attribution. Make small, focused commits with accurate messages that include checks actually run (e.g. "12/12 tests passed"). Never claim a check passed unless you ran it.
- Never commit `.env`, API keys, cached HTML, model weights, or other generated files. Add a `.gitignore` early.
- Report failures honestly. Never weaken or skip tests to make them pass.
- After each milestone below: commit, summarize what changed and what checks you ran, then STOP and wait for my go-ahead.

## Design

**Data:** ORS chapters 536, 537, 538, 539, and 540 (core water rights law), one HTML page per chapter at `https://www.oregonlegislature.gov/bills_laws/ors/ors537.html` (same pattern for each chapter). Verify these URLs load before relying on them.

**Stack:** Python 3.11+, Postgres with the pgvector extension, a small local open-source English embedding model via sentence-transformers (check the docs and choose a well-supported small model, e.g. BAAI/bge-small-en-v1.5; justify the choice), FastAPI serving one static HTML page, plus one of the two answer backends below.

**Config** (provide `.env.example` with all of these):

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_BACKEND` | `ollama` | `ollama` or `anthropic` |
| `OLLAMA_HOST` | `http://localhost:11434` | local Ollama server |
| `OLLAMA_MODEL` | pick one, see below | local model tag |
| `ANTHROPIC_API_KEY` | unset | only needed for the anthropic backend |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | |

Fail at startup with a clear message if the selected backend's settings are missing, rather than failing mid-question.

**Security constraints (these mirror the production requirements):**

- Embeddings are computed locally, always, under both backends.
- Retrieved document text may go only to the configured backend. No third-party telemetry, tracing, or logging services.
- Don't log full prompts or retrieved text by default.
- The model gets no tools: no web access, no file writes. Read-only question answering.

**Schema:** one `sections` table with section_number (unique, e.g. "537.130"), chapter, heading, text, source_url, edition (read from the page), allowed_groups (text array, empty = public), embedding (vector), and a generated tsvector column. Add an HNSW index on the embedding and a GIN index on the tsvector.

**Retrieval:** a single function, `search(question, user_groups) -> list of results`, with each result carrying section number, heading, text, and URL.

1. If the question contains an ORS citation (e.g. "537.545"), return that section first.
2. Otherwise run full-text search and vector search (top 20 each), merge with reciprocal rank fusion (k=60), and return the top 8.
3. Permission filtering happens inside the SQL query: a row is visible if allowed_groups is empty or overlaps user_groups. Never filter after retrieval or via the prompt.

**Answering:** one function, `answer(question, results) -> (text, cited_section_numbers)`, that dispatches on `LLM_BACKEND`. Both backends share the same system prompt: answer only from the provided sections; say plainly when they don't answer the question; cite section numbers like "ORS 537.130"; this is general information, not legal advice. The app returns the answer, the cited section numbers, and the full list of retrieved sections (the "find documents" feature).

- **Ollama backend.** Read the Ollama docs for the current REST API and use it directly over HTTP; don't add an SDK unless the docs show a clear reason. Format the retrieved sections into the prompt as a numbered list with section number, heading, and text. Since there are no structured citations, extract cited sections by scanning the answer text for section numbers and keeping only those that were actually retrieved. That intersection step matters: it means a section the model invented gets dropped rather than shown as a source.
- **Anthropic backend.** Send the retrieved sections as search result content blocks with citations enabled (confirm the exact format in the docs), and read the cited sections from the response's citation data rather than by parsing text.

## Milestones

**0. Plan.** Read the docs listed above. Fetch one chapter page and inspect its real HTML structure (section numbers, headings, repealed or renumbered sections, edition marker). Propose a short plan and file layout. Stop.

**1. Scaffold.** pyproject.toml, Postgres setup, schema creation, `.gitignore`, `.env.example`, and a README with setup steps. For Postgres, use Docker Compose with the official pgvector image, and document the direct-install alternative in the README for anyone avoiding Docker Desktop. Verify Postgres starts and the schema applies. Stop.

**2. Ingest.** A script that fetches the five chapters (caching raw HTML in a gitignored folder), parses one row per section, embeds, and upserts. Decide how to handle repealed and renumbered sections and explain the choice. Add parser unit tests using small saved HTML fixtures. Print section counts per chapter and three sample parsed sections. Stop so I can eyeball the chunks.

**3. Search.** Implement `search()` as designed. Add tests for citation detection, RRF merging, and permission filtering (insert a test row with allowed_groups set and confirm it is hidden from other users). Stop.

**4. Evaluate retrieval.** Create `evals/questions.jsonl` with 25 questions. Write each question by reading a specific section first, phrase it the way a non-lawyer would ask (don't copy the section heading), and record the expected section number(s). Write a script that reports how often an expected section appears in the top 8, and lists the misses. Run it and report the real numbers. Stop, because I will review the questions for accuracy.

**5. Answer, Ollama backend.** Check whether Ollama is installed and reachable; if not, give me install instructions and stop. Recommend a model that fits this machine, checking the Ollama model library for what's current rather than relying on memory, and say what you're trading off. Implement `answer()` with the Ollama path plus a CLI command: `ask "question"`. Unit-test the citation extraction and the invented-section filtering with fake model output, so those work without a running model. Show two example runs, including one question the statutes don't answer. Stop.

**6. Answer, Anthropic backend.** Add the Claude path to `answer()`. Keep the diff small: the retrieval, prompt, and CLI must not change. If `ANTHROPIC_API_KEY` isn't set, say so and stop rather than half-implementing. Run the same two example questions and show the two backends' answers side by side, noting quality differences. Stop.

**7. Web page.** A FastAPI endpoint plus one static HTML page: question box, answer, cited sections, the retrieved sections list with links to the source pages, which backend answered, and a visible "not legal advice" note. Stop and give a final summary covering what was built, key decisions, all checks run with results, and known limitations.
