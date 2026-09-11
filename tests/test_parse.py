"""Unit tests for orswater.parse against a small hand-built HTML fixture that mirrors
the real ORS chapter structure (verified against the live chapter 536/538/540 pages):
a leading plain-text section index, an ALL-CAPS division header, a normal section
spanning several paragraphs, repealed/renumbered/reserved sections, a "Note:"
annotation, and the future-effective-date reprint edge case.
"""

from __future__ import annotations

import pathlib

import pytest

from orswater.parse import dedupe_sections, parse_chapter

FIXTURE = (pathlib.Path(__file__).parent / "fixtures" / "sample_chapter.html").read_text()


@pytest.fixture
def parsed():
    sections, edition = parse_chapter(FIXTURE, chapter=538)
    return sections, edition


def _get(sections, number):
    matches = [s for s in sections if s.section_number == number]
    assert len(matches) == 1, f"expected exactly one row for {number}, got {len(matches)}"
    return matches[0]


def test_edition_extracted(parsed):
    _, edition = parsed
    assert edition == "2025 EDITION"


def test_index_and_division_header_are_not_sections(parsed):
    sections, _ = parsed
    # The plain-text index line and "GENERAL PROVISIONS" header must not become
    # their own (bogus) rows: only real section numbers, plus the intentional
    # 538.905 reprint duplicate, should show up.
    assert len(sections) == 6  # 901..904, 905 (future) and 905 (reprint)
    assert {s.section_number for s in sections} == {
        "538.901", "538.902", "538.903", "538.904", "538.905",
    }


def test_normal_section_collects_all_continuation_paragraphs(parsed):
    sections, _ = parsed
    s = _get(sections, "538.901")
    assert s.heading == "A normal section heading."
    assert not s.excluded
    assert "(1) This is the first sentence" in s.text
    assert "(a) This is a continuation subsection." in s.text
    assert "(b) This is another continuation subsection." in s.text


def test_repealed_section_is_excluded(parsed):
    sections, _ = parsed
    s = _get(sections, "538.902")
    assert s.heading is None
    assert s.excluded
    assert s.text == "[Repealed by 1985 c.2 §1]"


def test_renumbered_section_is_excluded(parsed):
    sections, _ = parsed
    s = _get(sections, "538.903")
    assert s.excluded
    assert "Renumbered" in s.text


def test_reserved_section_is_excluded(parsed):
    sections, _ = parsed
    s = _get(sections, "538.904")
    assert s.excluded
    assert "Reserved" in s.text


def test_note_annotation_is_not_a_section(parsed):
    sections, _ = parsed
    assert all(s.section_number != "Note:" for s in sections)


def test_future_dated_reprint_produces_two_raw_rows(parsed):
    sections, _ = parsed
    reprints = [s for s in sections if s.section_number == "538.905"]
    assert len(reprints) == 2
    future, reprint = reprints
    assert future.heading == "A section with a future amendment."
    assert not future.excluded
    assert reprint.heading is None  # the bare "538.905." reprint has no heading of its own
    assert not reprint.excluded  # it has real body text, not a bracketed note
    assert "currently operative" in reprint.text


def test_dedupe_collapses_reprint_and_keeps_the_operative_text():
    sections, _ = parse_chapter(FIXTURE, chapter=538)
    merged, notes = dedupe_sections(sections)

    numbers = [s.section_number for s in merged]
    assert numbers.count("538.905") == 1
    assert any("538.905" in note for note in notes)

    s = _get(merged, "538.905")
    # Heading backfilled from the future printing; text kept from the operative one.
    assert s.heading == "A section with a future amendment."
    assert "currently operative" in s.text
    assert not s.excluded


def test_dedupe_is_a_no_op_when_there_are_no_duplicates():
    sections, _ = parse_chapter(FIXTURE, chapter=538)
    non_reprint = [s for s in sections if s.section_number != "538.905"]
    merged, notes = dedupe_sections(non_reprint)
    assert merged == non_reprint
    assert notes == []
