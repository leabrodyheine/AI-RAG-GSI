"""FastAPI app for the web page (M6): one JSON endpoint plus the built React frontend.

``POST /api/ask`` is the only API route -- it just calls :func:`orswater.answer.answer`,
the same function the CLI uses, so both surfaces share identical retrieval, permission
filtering, and backend selection. The frontend (``web/``, a separate React + TypeScript
project built with Vite) is served as static files from ``web/dist`` once built; run
``cd web && npm install && npm run build`` first, or ``npm run dev`` for local
development (its dev server proxies ``/api`` to this app -- see ``web/vite.config.ts``).

No document text is logged here; only field access.
"""

from __future__ import annotations

import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .answer import MissingAnthropicCredentialsError, OllamaUnavailableError, answer
from .db import connect

app = FastAPI(title="Oregon Water Law RAG")


class AskRequest(BaseModel):
    question: str
    groups: list[str] = Field(default_factory=list)


class CitationOut(BaseModel):
    section_number: str
    heading: str
    cited_text: str
    url: str | None = None


class RetrievedSectionOut(BaseModel):
    section_number: str
    heading: str
    url: str


class AskResponse(BaseModel):
    backend: str
    text: str
    citations: list[CitationOut]
    retrieved_sections: list[RetrievedSectionOut]


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    conn = connect()
    try:
        result = answer(conn, req.question, req.groups)
    except (MissingAnthropicCredentialsError, OllamaUnavailableError) as e:
        # A configuration problem (ANSWER_BACKEND=anthropic with no real key, or
        # ANSWER_BACKEND=ollama with no reachable server), not a question the statutes
        # don't answer -- 503 rather than a normal answer payload.
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        conn.close()

    # retrieved_sections carries the source URL; citations don't (Citation is shared with
    # the CLI, which has no use for it), so join them here for the "clickable citations"
    # requirement.
    url_by_section = {r.section_number: r.url for r in result.retrieved_sections}

    return AskResponse(
        backend=result.backend,
        text=result.text,
        citations=[
            CitationOut(
                section_number=c.section_number,
                heading=c.heading,
                cited_text=c.cited_text,
                url=url_by_section.get(c.section_number),
            )
            for c in result.citations
        ],
        retrieved_sections=[
            RetrievedSectionOut(section_number=r.section_number, heading=r.heading, url=r.url)
            for r in result.retrieved_sections
        ],
    )


_DIST = pathlib.Path(__file__).resolve().parents[2] / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
else:

    @app.get("/")
    def _frontend_not_built() -> dict:
        return {
            "detail": (
                "Frontend not built yet. Run `cd web && npm install && npm run build`, "
                "then restart this app -- or run `npm run dev` in web/ for local "
                "development (its dev server proxies /api to this app on :8000)."
            )
        }
