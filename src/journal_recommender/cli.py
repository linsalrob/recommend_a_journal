"""Command-line entry points for journal recommender maintenance."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from journal_recommender.indexing import DEFAULT_INDEX_PATH, rebuild_index
from journal_recommender.manuscript import validate_manuscript_file
from journal_recommender.schema import validate_journal_file
from journal_recommender.scoring import rank_journals_from_files
from journal_recommender.updating import (
    generate_report_from_latest,
    run_journal_update,
)

DEFAULT_JOURNAL_PATH = Path("data/journals.yaml")
DEFAULT_CACHE_DIR = Path("data_raw/cache")
DEFAULT_REPORT_PATH = Path("reports/journal_database_changed.md")
DEFAULT_RECOMMENDATION_PATH = Path("reports/example_journal_recommendation.md")


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

    update_parser = subparsers.add_parser(
        "update-journals",
        help="Check journal URLs, Crossref metadata, and APC sources.",
    )
    update_parser.add_argument("--journals", default=DEFAULT_JOURNAL_PATH, type=Path)
    update_parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, type=Path)
    update_parser.add_argument("--report", default=DEFAULT_REPORT_PATH, type=Path)
    update_parser.add_argument("--delay-seconds", default=5.0, type=float)
    update_parser.add_argument(
        "--skip-crossref",
        action="store_true",
        help="Skip Crossref API lookups.",
    )

    index_parser = subparsers.add_parser(
        "rebuild-index",
        help="Rebuild the lightweight journal JSONL retrieval corpus.",
    )
    index_parser.add_argument("--journals", default=DEFAULT_JOURNAL_PATH, type=Path)
    index_parser.add_argument("--out", default=DEFAULT_INDEX_PATH, type=Path)

    report_parser = subparsers.add_parser(
        "report-changes",
        help="Regenerate the Markdown report from the latest update summary.",
    )
    report_parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, type=Path)
    report_parser.add_argument("--report", default=DEFAULT_REPORT_PATH, type=Path)
    report_parser.add_argument("--index", default=DEFAULT_INDEX_PATH, type=Path)

    manuscript_parser = subparsers.add_parser(
        "validate-manuscript",
        help="Validate a structured manuscript feature YAML file.",
    )
    manuscript_parser.add_argument("path", type=Path)

    rank_parser = subparsers.add_parser(
        "rank-journals",
        help="Rank journals for a structured manuscript feature YAML file.",
    )
    rank_parser.add_argument("--manuscript", required=True, type=Path)
    rank_parser.add_argument("--journals", default=DEFAULT_JOURNAL_PATH, type=Path)
    rank_parser.add_argument("--out", default=DEFAULT_RECOMMENDATION_PATH, type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-journals":
        journals = validate_journal_file(args.path)
        print(f"Validated {len(journals)} journal records from {args.path}")
        return 0

    if args.command == "update-journals":
        trigger = os.environ.get("GITHUB_EVENT_NAME", "local")
        report = run_journal_update(
            journals_path=args.journals,
            cache_dir=args.cache_dir,
            report_path=args.report,
            delay_seconds=args.delay_seconds,
            trigger=trigger,
            check_crossref=not args.skip_crossref,
        )
        print(
            "Checked "
            f"{report.journals_checked} journals, "
            f"{len(report.url_results)} URLs; "
            f"report written to {args.report}"
        )
        return 0

    if args.command == "rebuild-index":
        count = rebuild_index(args.journals, args.out)
        print(f"Rebuilt index for {count} journals at {args.out}")
        return 0

    if args.command == "report-changes":
        report = generate_report_from_latest(args.cache_dir, args.report, args.index)
        print(
            "Generated journal database change report "
            f"for {report.journals_checked} journals at {args.report}"
        )
        return 0

    if args.command == "validate-manuscript":
        manuscript = validate_manuscript_file(args.path)
        title = manuscript.title or args.path.name
        print(f"Validated manuscript feature file for {title}")
        return 0

    if args.command == "rank-journals":
        recommendations = rank_journals_from_files(
            manuscript_path=args.manuscript,
            journals_path=args.journals,
            report_path=args.out,
        )
        print(
            "Ranked "
            f"{len(recommendations.scores)} journals; "
            f"top recommendation is {recommendations.scores[0].journal}; "
            f"report written to {args.out}"
        )
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
