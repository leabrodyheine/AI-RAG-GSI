"""Parse one ORS chapter HTML page into per-section rows.

The Oregon Legislature publishes each chapter as Word-exported HTML. Verified against
real chapter pages (536 and 538): a body section starts with a paragraph whose leading
run is bold -- ``<b><span>NUMBER heading.</span></b>`` -- followed by the start of the
section's text as a sibling, non-bold span in the *same* paragraph; continuation
paragraphs are plain (non-bold) until the next bold paragraph. The chapter's leading
section index, ALL-CAPS division headers, and preface text are all non-bold, so they are
skipped naturally: no section is "open" while they are read.

Repealed, renumbered, and reserved sections carry a bold paragraph with *only* the
section number (no heading text), followed by a bracketed note instead of body text
(e.g. ``[Repealed by 1975 c.581 §29]``). Those are still parsed -- callers may want to
know a number exists and why it has no text -- but are flagged ``excluded`` so ingest.py
can leave them out of the embedded corpus.

A bold paragraph that does *not* start with a section number (e.g. a legislative
``Note:`` annotation between sections) closes whatever section was open and is otherwise
ignored.

Some sections that have a future-dated amendment print *twice*: once under a "Note:"
explaining the amendment is not yet operative, then again -- reusing the bare number as
the bold text (e.g. ``536.045.`` with no heading) -- with the text that is "operative
until" that future date "for the user's convenience" (the Legislature's own wording).
``dedupe_sections`` collapses each such pair back into one row, keeping the printing
that carries real body text and is listed *last* (Oregon's own convention is to place
the presently-operative version after the future one).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Chapters 536-540 (the water-law chapters this prototype covers) all number their
# sections 5[3-4]d.ddd(d).
SECTION_NUMBER_RE = re.compile(r"^(5[3-4]\d\.\d{3,4})\s*(.*)$", re.DOTALL)
EDITION_RE = re.compile(r"(\d{4}\s+EDITION)")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedSection:
    section_number: str
    chapter: int
    heading: str | None
    text: str
    excluded: bool


def _clean(text: str) -> str:
    """Collapse the hard line-wraps and non-breaking spaces Word's export leaves behind."""
    return WHITESPACE_RE.sub(" ", text).strip()


def parse_chapter(html: str, chapter: int) -> tuple[list[ParsedSection], str | None]:
    """Parse one chapter's HTML into (sections, edition)."""
    soup = BeautifulSoup(html, "lxml")
    edition_match = EDITION_RE.search(_clean(soup.get_text()))
    edition = edition_match.group(1) if edition_match else None

    sections: list[ParsedSection] = []
    number: str | None = None
    heading: str | None = None
    body_parts: list[str] = []

    def flush() -> None:
        if number is None:
            return
        text = _clean(" ".join(body_parts))
        # A real repealed/renumbered/reserved note is the *only* body content and always
        # opens with "[". A section with a real heading always has substantive prose --
        # this also holds for the headingless "operative until" reprint described above,
        # whose body is ordinary statute text, not a bracketed note.
        excluded = heading is None and text.startswith("[")
        sections.append(
            ParsedSection(
                section_number=number,
                chapter=chapter,
                heading=heading,
                text=text,
                excluded=excluded,
            )
        )

    for p in soup.find_all("p"):
        bold = p.find("b")

        if bold is not None:
            flush()
            number = None
            heading = None
            body_parts = []

            match = SECTION_NUMBER_RE.match(_clean(bold.get_text()))
            if match is None:
                continue  # a "Note:" annotation or similar -- not a section

            number = match.group(1)
            heading_text = _clean(match.group(2))
            # A bare trailing "." (as in "536.045.") isn't a heading -- it's the
            # reprint case above wearing the number's own punctuation.
            heading = heading_text if any(ch.isalpha() for ch in heading_text) else None

            # Everything after </b> within the same paragraph is the start of the body.
            remainder = _clean("".join(sib.get_text() for sib in bold.next_siblings))
            if remainder:
                body_parts.append(remainder)
            continue

        if number is None:
            continue  # index entry, division header, or preface text -- no section open

        text = _clean(p.get_text())
        if not text:
            continue  # spacer paragraph (a lone "&nbsp;")

        if text.isupper():
            # An ALL-CAPS division header (e.g. "GENERAL PROVISIONS") between sections,
            # not body text -- these use the same plain paragraph style as continuation
            # text, so the only reliable signal is that real body text always has
            # lowercase words. Close whatever section was open.
            flush()
            number = None
            heading = None
            body_parts = []
            continue

        body_parts.append(text)

    flush()
    return sections, edition


def dedupe_sections(sections: list[ParsedSection]) -> tuple[list[ParsedSection], list[str]]:
    """Collapse duplicate printings of the same section number into one row.

    Returns the deduplicated list plus a note per collapsed section number, so callers
    can report what happened instead of silently dropping a row.
    """
    by_number: dict[str, list[ParsedSection]] = {}
    order: list[str] = []
    for s in sections:
        if s.section_number not in by_number:
            order.append(s.section_number)
        by_number.setdefault(s.section_number, []).append(s)

    merged: list[ParsedSection] = []
    notes: list[str] = []
    for number in order:
        group = by_number[number]
        if len(group) == 1:
            merged.append(group[0])
            continue

        substantive = [s for s in group if not s.text.startswith("[")]
        chosen = substantive[-1] if substantive else group[-1]
        if chosen.heading is None:
            real_heading = next((s.heading for s in group if s.heading), None)
            if real_heading is not None:
                chosen = ParsedSection(
                    section_number=chosen.section_number,
                    chapter=chosen.chapter,
                    heading=real_heading,
                    text=chosen.text,
                    excluded=chosen.excluded,
                )
        merged.append(chosen)
        notes.append(
            f"{number}: collapsed {len(group)} printings (future-effective-date reprint)"
        )

    return merged, notes
