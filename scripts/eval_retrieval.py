"""Milestone 4: measure how often orswater.search() surfaces the right ORS section.

Reads evals/questions.jsonl (one {"question": ..., "expected_sections": [...]} per line --
each question was written by hand after reading one real, currently-ingested section, phrased
the way a non-lawyer would actually ask it, with no literal ORS citation in the question text
so it exercises ranked search rather than the citation-lookup shortcut). For each question,
runs the real search() against the live database with user_groups=[] and checks whether any
expected section number appears in the top 8 results. Prints a hit-rate summary and the full
list of misses (with what was returned instead) so failures are visible, not just the score.

Usage: python -m scripts.eval_retrieval
"""

from __future__ import annotations

import json
from pathlib import Path

from orswater.db import connect
from orswater.search import search

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "evals" / "questions.jsonl"


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    questions = load_questions()
    conn = connect()

    hits = 0
    misses = []
    for item in questions:
        question = item["question"]
        expected = set(item["expected_sections"])
        results = search(conn, question, user_groups=[])
        returned = [r.section_number for r in results]
        if expected & set(returned):
            hits += 1
        else:
            misses.append((question, expected, returned))

    conn.close()

    total = len(questions)
    print(f"Top-8 hit rate: {hits}/{total} ({hits / total:.0%})\n")

    if misses:
        print(f"Misses ({len(misses)}):")
        for question, expected, returned in misses:
            print(f"  Q: {question}")
            print(f"     expected: {sorted(expected)}")
            print(f"     got:      {returned}")
    else:
        print("No misses.")


if __name__ == "__main__":
    main()
