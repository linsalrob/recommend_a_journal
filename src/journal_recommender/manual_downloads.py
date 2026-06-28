"""Manual download queue generation after local manual-source ingestion."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from journal_recommender.manual_sources import (
    ManualSource,
    ParsedManualSource,
    infer_source_type,
    infer_target_fields,
)
from journal_recommender.schema import JournalRecord, validate_journal_file
from journal_recommender.updating import LATEST_REPORT_FILE, URL_CACHE_FILE


@dataclass
class ManualQueueEntry:
    journal: str
    source_type: str
    url: str
    local_file: str
    automated_status: str
    status_code: int | None
    quality_flags: list[str]
    reason: str
    target_fields: list[str]
    status: str = "needs_manual_download"


def generate_manual_download_queue(
    manifest_sources: list[ManualSource],
    parsed_sources: list[ParsedManualSource],
    journals_path: Path,
    cache_dir: Path,
    queue_yaml: Path,
    queue_report: Path,
) -> list[ManualQueueEntry]:
    journals = validate_journal_file(journals_path)
    entries: list[ManualQueueEntry] = []
    entries.extend(queue_entries_from_manifest(parsed_sources))
    entries.extend(
        queue_entries_from_cache(manifest_sources, parsed_sources, journals, cache_dir)
    )
    entries.extend(
        queue_entries_for_empty_fields(manifest_sources, parsed_sources, journals)
    )
    entries = dedupe_entries(entries)
    write_queue_yaml(entries, queue_yaml)
    write_queue_report(entries, parsed_sources, manifest_sources, queue_report)
    return entries


def queue_entries_from_manifest(
    parsed_sources: list[ParsedManualSource],
) -> list[ManualQueueEntry]:
    entries = []
    for parsed in parsed_sources:
        if parsed.status == "parsed":
            continue
        source = parsed.source
        status = (
            "manifested_but_missing_local_file"
            if parsed.status == "missing_local_file"
            else "manifested_but_parsing_failed"
        )
        reason = (
            "Manifest entry has no local file yet."
            if parsed.status == "missing_local_file"
            else f"Local file could not be parsed: {parsed.error}"
        )
        entries.append(
            ManualQueueEntry(
                journal=source.journal,
                source_type=source.source_type,
                url=source.url,
                local_file=str(source.local_file),
                automated_status=parsed.status,
                status_code=None,
                quality_flags=[],
                reason=reason,
                target_fields=source.target_fields,
                status=status,
            )
        )
    return entries


def queue_entries_from_cache(
    manifest_sources: list[ManualSource],
    parsed_sources: list[ParsedManualSource],
    journals: list[JournalRecord],
    cache_dir: Path,
) -> list[ManualQueueEntry]:
    satisfied_urls = {
        parsed.source.url for parsed in parsed_sources if parsed.status == "parsed"
    }
    manifest_urls = {source.url for source in manifest_sources}
    cache_entries = read_json(cache_dir / URL_CACHE_FILE)
    latest_report = read_json(cache_dir / LATEST_REPORT_FILE)
    url_to_journal = collect_journal_urls(journals)
    entries: list[ManualQueueEntry] = []

    report_results = {
        result.get("url"): result for result in latest_report.get("url_results", [])
    }
    for url, cache_entry in cache_entries.items():
        if url in satisfied_urls or url in manifest_urls:
            continue
        report_entry = report_results.get(url, {})
        status_code = cache_entry.get("status_code")
        quality_flags = list(cache_entry.get("content_quality_flags", []) or [])
        automated_status = report_entry.get("status") or automated_status_from_cache(
            cache_entry
        )
        if not needs_manual_download(automated_status, status_code, quality_flags):
            continue
        journal = url_to_journal.get(url, "")
        source_type = infer_source_type(url)
        entries.append(
            ManualQueueEntry(
                journal=journal,
                source_type=source_type,
                url=url,
                local_file=suggest_local_file(journal, source_type, url),
                automated_status=automated_status,
                status_code=status_code,
                quality_flags=quality_flags,
                reason=reason_from_status(automated_status, status_code, quality_flags),
                target_fields=infer_target_fields(source_type),
            )
        )
    return entries


def queue_entries_for_empty_fields(
    manifest_sources: list[ManualSource],
    parsed_sources: list[ParsedManualSource],
    journals: list[JournalRecord],
) -> list[ManualQueueEntry]:
    satisfied_urls = {
        parsed.source.url for parsed in parsed_sources if parsed.status == "parsed"
    }
    manifest_urls = {source.url for source in manifest_sources}
    entries = []
    for journal in journals:
        for source_type, url, fields in important_empty_source_urls(journal):
            if not url or url in satisfied_urls or url in manifest_urls:
                continue
            entries.append(
                ManualQueueEntry(
                    journal=journal.journal,
                    source_type=source_type,
                    url=url,
                    local_file=suggest_local_file(journal.journal, source_type, url),
                    automated_status="not_checked",
                    status_code=None,
                    quality_flags=[],
                    reason=(
                        "Important target fields remain empty and a source URL "
                        "is known."
                    ),
                    target_fields=fields,
                )
            )
    return entries


def important_empty_source_urls(
    journal: JournalRecord,
) -> list[tuple[str, str, list[str]]]:
    entries: list[tuple[str, str, list[str]]] = []
    if not journal.article_types and journal.author_instructions_url:
        entries.append(
            (
                "author_instructions",
                journal.author_instructions_url,
                ["author_instructions_url", "article_types"],
            )
        )
    if not journal.scope_tags and journal.aims_scope_url:
        entries.append(
            (
                "aims_scope",
                journal.aims_scope_url,
                ["aims_scope_url", "scope_tags", "suitable_for"],
            )
        )
    if not journal.open_access.model and journal.open_access.url:
        entries.append(("open_access", journal.open_access.url, ["open_access"]))
    return entries


def collect_journal_urls(journals: list[JournalRecord]) -> dict[str, str]:
    mapping = {}
    for journal in journals:
        urls = [
            journal.homepage_url,
            journal.aims_scope_url,
            journal.author_instructions_url,
            journal.data_policy.url,
            journal.code_policy.url,
            journal.open_access.url,
        ]
        urls.extend(evidence.url for evidence in journal.source_evidence)
        for url in urls:
            if url and not is_manually_curated_only(journal, url):
                mapping.setdefault(url, journal.journal)
    return mapping


def is_manually_curated_only(journal: JournalRecord, url: str) -> bool:
    for evidence in journal.source_evidence:
        if evidence.url != url:
            continue
        marker = " ".join([evidence.label, evidence.notes]).lower()
        if "manually curated only" in marker:
            return True
    return False


def automated_status_from_cache(entry: dict[str, Any]) -> str:
    status_code = entry.get("status_code")
    flags = set(entry.get("content_quality_flags", []) or [])
    if status_code in {403, 429}:
        return "blocked"
    if entry.get("error"):
        return "failed"
    if flags & {
        "empty_body",
        "very_short_body",
        "generic_error_page",
        "blocked_or_challenge_page",
        "duplicate_hash_across_many_urls",
        "redirect_or_consent_page",
    }:
        return "suspicious"
    if status_code != 200:
        return "failed"
    return "unchanged"


def needs_manual_download(
    status: str,
    status_code: int | None,
    quality_flags: list[str],
) -> bool:
    if status in {"blocked", "failed", "suspicious"}:
        return True
    if status_code is not None and status_code != 200:
        return True
    return bool(
        set(quality_flags)
        & {
            "empty_body",
            "very_short_body",
            "generic_error_page",
            "blocked_or_challenge_page",
            "duplicate_hash_across_many_urls",
            "redirect_or_consent_page",
        }
    )


def reason_from_status(
    status: str,
    status_code: int | None,
    quality_flags: list[str],
) -> str:
    if status == "blocked":
        return f"Automated fetch returned HTTP {status_code}."
    if status == "suspicious":
        return (
            "Automated fetch produced suspicious content: "
            f"{', '.join(quality_flags)}."
        )
    if status == "failed":
        return "Automated fetch failed and no parsed local file is available."
    if status_code is not None and status_code != 200:
        return f"Automated fetch returned non-200 status {status_code}."
    return "Manual review recommended."


def suggest_local_file(journal: str, source_type: str, url: str) -> str:
    base = slugify(journal or domain_slug(url))
    source = slugify(source_type)
    return f"data_manual/pages/{base}_{source}.html"


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "manual_source"


def domain_slug(url: str) -> str:
    return url.split("//")[-1].split("/")[0]


def dedupe_entries(entries: list[ManualQueueEntry]) -> list[ManualQueueEntry]:
    deduped: dict[tuple[str, str], ManualQueueEntry] = {}
    for entry in entries:
        deduped.setdefault((entry.journal, entry.url), entry)
    return sorted(
        deduped.values(),
        key=lambda item: (item.journal, item.source_type, item.url),
    )


def write_queue_yaml(entries: list[ManualQueueEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"manual_download_queue": [entry.__dict__ for entry in entries]}
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)


def write_queue_report(
    entries: list[ManualQueueEntry],
    parsed_sources: list[ParsedManualSource],
    manifest_sources: list[ManualSource],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_queue_report(entries, parsed_sources, manifest_sources),
        encoding="utf-8",
    )


def render_queue_report(
    entries: list[ManualQueueEntry],
    parsed_sources: list[ParsedManualSource],
    manifest_sources: list[ManualSource],
) -> str:
    parsed = [item for item in parsed_sources if item.status == "parsed"]
    missing = [item for item in parsed_sources if item.status == "missing_local_file"]
    failed = [item for item in parsed_sources if item.status == "parsing_failed"]
    lines = [
        "# Manual Download Queue",
        "",
        "## Summary",
        "",
        f"- Manifest entries: {len(manifest_sources)}",
        f"- Local files found: {len(parsed) + len(failed)}",
        f"- Local files parsed: {len(parsed)}",
        f"- Local files missing: {len(missing)}",
        f"- Local files failed parsing: {len(failed)}",
        f"- URLs still needing manual download: {len(entries)}",
        "",
        "## Files Parsed This Run",
        "",
        "| Journal | Source type | Local file | Suggestions generated |",
        "| --- | --- | --- | ---: |",
    ]
    if parsed:
        for item in parsed:
            lines.append(
                f"| {item.source.journal} | {item.source.source_type} | "
                f"{item.source.local_file} | {item.suggestions_generated} |"
            )
    else:
        lines.append("|  |  |  |  |")
    lines.extend(
        [
            "",
            "## Missing Local Files From Manifest",
            "",
            "| Journal | Source type | URL | Expected local file |",
            "| --- | --- | --- | --- |",
        ]
    )
    if missing:
        for item in missing:
            lines.append(
                f"| {item.source.journal} | {item.source.source_type} | "
                f"{item.source.url} | {item.source.local_file} |"
            )
    else:
        lines.append("|  |  |  |  |")
    lines.extend(
        [
            "",
            "## New URLs To Add To Manifest",
            "",
            "| Journal | Source type | HTTP | Status | URL | "
            "Suggested local file | Reason |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    new_entries = [
        entry
        for entry in entries
        if entry.status not in {
            "manifested_but_missing_local_file",
            "manifested_but_parsing_failed",
        }
    ]
    if new_entries:
        for entry in new_entries:
            lines.append(
                f"| {entry.journal} | {entry.source_type} | "
                f"{entry.status_code or ''} | {entry.automated_status} | "
                f"{entry.url} | {entry.local_file} | {entry.reason} |"
            )
    else:
        lines.append("|  |  |  |  |  |  |  |")
    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "1. Download the missing pages manually in a browser.",
            "2. Save them to the suggested local paths.",
            "3. Add or confirm entries in `data_manual/manifest.yaml`.",
            "4. Re-run `process-manual-sources`.",
            "",
        ]
    )
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}
