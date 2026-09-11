"""Fetch, parse, embed, and upsert the ORS water-law chapters into ``sections``.

Run as ``python -m orswater.ingest``. Prints per-chapter counts and a few sample
sections rather than logging full section text by default (the README's logging rule).
"""

from __future__ import annotations

from .db import connect
from .embed import embed_passages
from .fetch import fetch_chapter
from .parse import dedupe_sections, parse_chapter

CHAPTERS = [536, 537, 538, 539, 540]
SOURCE_URL_TEMPLATE = "https://www.oregonlegislature.gov/bills_laws/ors/ors{chapter}.html"


def ingest_chapter(conn, chapter: int, *, use_cache: bool = True) -> dict:
    """Fetch, parse, embed, and upsert one chapter. Returns a small report dict."""
    html = fetch_chapter(chapter, use_cache=use_cache)
    raw, edition = parse_chapter(html, chapter)
    merged, merge_notes = dedupe_sections(raw)

    included = [s for s in merged if not s.excluded]
    excluded = [s for s in merged if s.excluded]

    source_url = SOURCE_URL_TEMPLATE.format(chapter=chapter)
    if included:
        # bge-small-en-v1.5 embeds heading + text together, matching what the
        # generated tsvector column indexes for full-text search.
        embeddings = embed_passages([f"{s.heading}\n{s.text}" for s in included])
    else:
        embeddings = []

    with conn.cursor() as cur:
        for section, embedding in zip(included, embeddings):
            cur.execute(
                """
                INSERT INTO sections
                    (section_number, chapter, heading, text, source_url, edition, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (section_number) DO UPDATE SET
                    chapter = EXCLUDED.chapter,
                    heading = EXCLUDED.heading,
                    text = EXCLUDED.text,
                    source_url = EXCLUDED.source_url,
                    edition = EXCLUDED.edition,
                    embedding = EXCLUDED.embedding
                """,
                (
                    section.section_number,
                    section.chapter,
                    section.heading,
                    section.text,
                    source_url,
                    edition,
                    embedding,
                ),
            )
    conn.commit()

    return {
        "chapter": chapter,
        "edition": edition,
        "included": included,
        "excluded": excluded,
        "merge_notes": merge_notes,
    }


def main() -> None:
    reports = []
    with connect() as conn:
        for chapter in CHAPTERS:
            report = ingest_chapter(conn, chapter)
            reports.append(report)

            print(
                f"chapter {chapter} ({report['edition']}): "
                f"{len(report['included'])} included, {len(report['excluded'])} excluded"
            )
            for note in report["merge_notes"]:
                print(f"  merged: {note}")
            for s in report["excluded"]:
                print(f"  excluded {s.section_number}: {s.text}")

    print()
    print("--- sample parsed sections ---")
    samples = [s for r in reports for s in r["included"]][:3]
    for s in samples:
        print(f"{s.section_number} -- {s.heading}")
        print(f"  {s.text[:200]}{'...' if len(s.text) > 200 else ''}")

    total_included = sum(len(r["included"]) for r in reports)
    total_excluded = sum(len(r["excluded"]) for r in reports)
    print()
    print(f"total: {total_included} included, {total_excluded} excluded")


if __name__ == "__main__":
    main()
