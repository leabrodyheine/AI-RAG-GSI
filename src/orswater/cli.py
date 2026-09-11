"""Command-line entry point.

Usage:
    orswater ask "<question>" [--groups g1,g2]

The answer backend is chosen by the ANSWER_BACKEND env var ("deterministic", the
default -- no API key or model needed; "ollama" -- requires a running local Ollama
server; or "anthropic" -- requires a real ANTHROPIC_API_KEY). See .env.example and the
README.
"""

from __future__ import annotations

import argparse
import sys

from .answer import MissingAnthropicCredentialsError, OllamaUnavailableError, answer
from .db import connect


def _run_ask(question: str, groups: list[str]) -> int:
    conn = connect()
    try:
        result = answer(conn, question, groups)
    except (MissingAnthropicCredentialsError, OllamaUnavailableError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"[backend: {result.backend}]")
    print(result.text)

    if result.citations:
        print("\nCited sections:")
        for c in result.citations:
            print(f"  ORS {c.section_number} — {c.heading}")

    if result.retrieved_sections:
        print("\nRetrieved sections:")
        for r in result.retrieved_sections:
            print(f"  ORS {r.section_number} — {r.heading} ({r.url})")

    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="orswater",
        description=(
            "Answer backend is set by the ANSWER_BACKEND env var: 'deterministic' "
            "(default, no API key or model needed), 'ollama' (requires a running local "
            "Ollama server), or 'anthropic' (requires ANTHROPIC_API_KEY)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    ask_parser = subparsers.add_parser("ask", help="Ask an Oregon water law question.")
    ask_parser.add_argument("question")
    ask_parser.add_argument(
        "--groups",
        default="",
        help="Comma-separated user groups (default: none, i.e. public access only).",
    )

    args = parser.parse_args(argv)

    if args.command != "ask":
        parser.print_help()
        return 0 if not argv else 1

    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    return _run_ask(args.question, groups)


if __name__ == "__main__":
    raise SystemExit(main())
