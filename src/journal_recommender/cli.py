"""Command-line entry points for journal recommender maintenance."""

from __future__ import annotations

import argparse
from pathlib import Path

from journal_recommender.schema import validate_journal_file

DEFAULT_JOURNAL_PATH = Path("data/journals.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="journal-recommender")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate-journals",
        help="Validate the curated journal YAML database.",
    )
    validate_parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_JOURNAL_PATH,
        type=Path,
        help="Path to journals.yaml.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-journals":
        journals = validate_journal_file(args.path)
        print(f"Validated {len(journals)} journal records from {args.path}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
