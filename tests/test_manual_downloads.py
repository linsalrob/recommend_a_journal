from __future__ import annotations

import json
from pathlib import Path

from journal_recommender.manual_downloads import (
    generate_manual_download_queue,
    suggest_local_file,
)
from journal_recommender.manual_sources import ManualSource, ParsedManualSource
from tests.test_manual_sources import write_minimal_journals


def test_queue_excludes_successfully_parsed_manifest_entry(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    source = ManualSource(
        journal="Example Journal",
        source_type="homepage_or_scope",
        url="https://example.org/journal",
        local_file=tmp_path / "manual.html",
        target_fields=["scope_tags"],
    )
    parsed = [ParsedManualSource(source=source, status="parsed", text="ok")]

    queue = generate_manual_download_queue(
        [source],
        parsed,
        journals,
        tmp_path / "cache",
        tmp_path / "queue.yaml",
        tmp_path / "queue.md",
    )

    assert queue == []


def test_queue_includes_manifested_missing_file(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    source = ManualSource(
        journal="Example Journal",
        source_type="homepage_or_scope",
        url="https://example.org/journal",
        local_file=tmp_path / "missing.html",
        target_fields=["scope_tags"],
    )
    parsed = [ParsedManualSource(source=source, status="missing_local_file")]

    queue = generate_manual_download_queue(
        [source],
        parsed,
        journals,
        tmp_path / "cache",
        tmp_path / "queue.yaml",
        tmp_path / "queue.md",
    )

    assert queue[0].status == "manifested_but_missing_local_file"


def test_queue_includes_manifested_parsing_failure(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    source = ManualSource(
        journal="Example Journal",
        source_type="homepage_or_scope",
        url="https://example.org/journal",
        local_file=tmp_path / "broken.pdf",
        target_fields=["scope_tags"],
    )
    parsed = [
        ParsedManualSource(
            source=source,
            status="parsing_failed",
            error="PDF parsing is not implemented.",
        )
    ]

    queue = generate_manual_download_queue(
        [source],
        parsed,
        journals,
        tmp_path / "cache",
        tmp_path / "queue.yaml",
        tmp_path / "queue.md",
    )

    assert queue[0].status == "manifested_but_parsing_failed"


def test_queue_includes_blocked_failed_suspicious_urls(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "url_cache.json").write_text(
        json.dumps(
            {
                "https://example.org/blocked": {
                    "status_code": 403,
                    "error": "HTTP 403",
                    "content_quality_flags": [],
                },
                "https://example.org/suspicious": {
                    "status_code": 200,
                    "error": "",
                    "content_quality_flags": ["very_short_body"],
                },
            }
        ),
        encoding="utf-8",
    )
    (cache / "latest_update_report.json").write_text("{}", encoding="utf-8")

    queue = generate_manual_download_queue(
        [],
        [],
        journals,
        cache,
        tmp_path / "queue.yaml",
        tmp_path / "queue.md",
    )

    statuses = {entry.automated_status for entry in queue}
    assert {"blocked", "suspicious"} <= statuses


def test_suggest_local_file_is_stable() -> None:
    assert (
        suggest_local_file(
            "Science Advances",
            "author_instructions",
            "https://example.org/authors",
        )
        == "data_manual/pages/science_advances_author_instructions.html"
    )
