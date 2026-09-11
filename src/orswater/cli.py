"""Command-line entry point. Subcommands (``ask``, ...) are added in later milestones."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    print("orswater: scaffold only, no commands yet. See README milestones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
