"""Add journal stubs from the manual manifest, without inventing facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import yaml

from journal_recommender.indexing import rebuild_index as rebuild_journal_index
from journal_recommender.manual_sources import load_manual_manifest
from journal_recommender.schema import JournalRecord, validate_journal_file
from journal_recommender.updating import (
    fetch_openalex_metadata,
    load_scimago_rows,
    match_scimago_row,
    scimago_metrics_from_row,
)

DEFAULT_SCIMAGO_PATH = Path("data/scimagojr_2025.csv")


@dataclass
class ManifestJournalStub:
    journal: str
    inferred_urls: dict[str, str] = field(default_factory=dict)
    source_urls: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    record: dict[str, Any] = field(default_factory=dict)
    scimago_matched: bool = False
    openalex_matched: bool = False


@dataclass
class ManifestJournalReport:
    manifest_journal_names: int
    existing_journals: int
    missing_journals: int
    added_journals: list[str] = field(default_factory=list)
    already_present_journals: list[str] = field(default_factory=list)
    stubs: list[ManifestJournalStub] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mode: str = "dry-run"
    scimago_updates: int = 0
    openalex_updates: int = 0
    rebuild_index: bool = False


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def current_access_date() -> str:
    return datetime.now(UTC).date().isoformat()


def load_existing_journal_records(journals_path: Path) -> list[dict[str, Any]]:
    with journals_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    if not isinstance(data, list):
        msg = "Journal database must be a YAML list of journal records."
        raise ValueError(msg)
    return data


def existing_journal_name_map(
    journals_path: Path,
) -> dict[str, str]:
    records = load_existing_journal_records(journals_path)
    return {
        normalize_name(str(record.get("journal", ""))): str(record.get("journal", ""))
        for record in records
        if str(record.get("journal", "")).strip()
    }


def manifest_journal_sources(manifest_path: Path) -> list[dict[str, Any]]:
    return [source.__dict__ for source in load_manual_manifest(manifest_path)]


def build_journal_stub_record(journal: str) -> dict[str, Any]:
    return JournalRecord.model_validate({"journal": journal}).model_dump(mode="python")


def infer_url_field(source_type: str) -> str | None:
    source_type = source_type.strip().casefold()
    if source_type == "homepage_or_scope":
        return "homepage_url"
    if source_type == "aims_scope":
        return "aims_scope_url"
    if source_type in {"author_instructions", "guide_for_authors"}:
        return "author_instructions_url"
    if source_type == "data_policy":
        return "data_policy.url"
    if source_type == "code_policy":
        return "code_policy.url"
    if source_type in {"apc", "open_access"}:
        return "open_access.url"
    return None


def build_manifest_journal_report(
    manifest_path: Path,
    journals_path: Path,
) -> ManifestJournalReport:
    sources = load_manual_manifest(manifest_path)
    existing = existing_journal_name_map(journals_path)
    seen_manifest_names: list[str] = []
    grouped_sources: dict[str, list[Any]] = {}
    canonical_names: dict[str, str] = {}

    for source in sources:
        normalized = normalize_name(source.journal)
        canonical_names.setdefault(normalized, source.journal)
        grouped_sources.setdefault(normalized, []).append(source)
        if normalized not in seen_manifest_names:
            seen_manifest_names.append(normalized)

    stubs: list[ManifestJournalStub] = []
    warnings: list[str] = []
    added_journals: list[str] = []
    already_present: list[str] = []

    for normalized in seen_manifest_names:
        journal = canonical_names[normalized]
        manifest_sources = grouped_sources[normalized]
        if normalized in existing:
            already_present.append(existing[normalized])
            continue
        stub = build_stub_from_manifest_sources(journal, manifest_sources)
        stubs.append(stub)
        added_journals.append(journal)
        warnings.extend(stub.warnings)

    return ManifestJournalReport(
        manifest_journal_names=len(seen_manifest_names),
        existing_journals=len(existing),
        missing_journals=len(stubs),
        added_journals=added_journals,
        already_present_journals=sorted(already_present),
        stubs=stubs,
        warnings=sorted(set(warnings)),
    )


def build_stub_from_manifest_sources(
    journal: str,
    sources: list[Any],
) -> ManifestJournalStub:
    record = build_journal_stub_record(journal)
    inferred_urls: dict[str, str] = {}
    source_urls: list[str] = []
    source_types: list[str] = []
    warnings: list[str] = []

    for source in sources:
        source_types.append(source.source_type)
        if source.url:
            source_urls.append(source.url)
        url_field = infer_url_field(source.source_type)
        if url_field is None:
            warnings.append(
                f"Ambiguous source type {source.source_type!r} for {journal}; "
                "no URL field inferred."
            )
            continue
        set_nested_url(record, url_field, source.url)
        inferred_urls[url_field] = source.url
        add_source_evidence(record, source.url)

    return ManifestJournalStub(
        journal=journal,
        inferred_urls=inferred_urls,
        source_urls=sorted(set(source_urls)),
        source_types=sorted(set(source_types)),
        warnings=sorted(set(warnings)),
        record=record,
    )


def add_source_evidence(record: dict[str, Any], source_url: str) -> None:
    if not source_url:
        return
    evidence = record.setdefault("source_evidence", [])
    entry = {
        "label": "Manual manifest source",
        "url": source_url,
        "accessed": current_access_date(),
        "notes": "Added from data_manual/manifest.yaml; requires manual curation.",
    }
    if not any(
        item.get("url") == source_url and item.get("label") == entry["label"]
        for item in evidence
    ):
        evidence.append(entry)


def set_nested_url(record: dict[str, Any], field_path: str, value: str) -> None:
    if not value:
        return
    if field_path == "homepage_url" and not record.get("homepage_url"):
        record["homepage_url"] = value
    elif field_path == "aims_scope_url" and not record.get("aims_scope_url"):
        record["aims_scope_url"] = value
    elif field_path == "author_instructions_url" and not record.get(
        "author_instructions_url"
    ):
        record["author_instructions_url"] = value
    elif field_path == "data_policy.url" and not record["data_policy"].get("url"):
        record["data_policy"]["url"] = value
    elif field_path == "code_policy.url" and not record["code_policy"].get("url"):
        record["code_policy"]["url"] = value
    elif field_path == "open_access.url" and not record["open_access"].get("url"):
        record["open_access"]["url"] = value


def write_journals(records: list[dict[str, Any]], journals_path: Path) -> None:
    journals_path.write_text(
        yaml.safe_dump(records, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def append_stubs_to_journals(
    journals_path: Path,
    stubs: list[ManifestJournalStub],
) -> list[dict[str, Any]]:
    records = load_existing_journal_records(journals_path)
    records.extend(stub.record for stub in stubs)
    write_journals(records, journals_path)
    return records


def enrich_manifest_stubs(
    stubs: list[ManifestJournalStub],
    scimago_path: Path = DEFAULT_SCIMAGO_PATH,
    openalex_opener: object | None = urlopen,
) -> tuple[int, int, list[str]]:
    scimago_updates = 0
    openalex_updates = 0
    warnings: list[str] = []

    if scimago_path.exists():
        rows = load_scimago_rows(scimago_path)
        for stub in stubs:
            journal = JournalRecord.model_validate(stub.record)
            row = match_scimago_row(journal, rows)
            if not row:
                continue
            metrics = scimago_metrics_from_row(row, 2025, scimago_path)
            stub.record["prestige_metrics"].update(metrics)
            stub.scimago_matched = True
            scimago_updates += 1

    for stub in stubs:
        journal = JournalRecord.model_validate(stub.record)
        result = fetch_openalex_metadata(
            journal,
            now=current_access_date(),
            opener=openalex_opener,
        )
        if result.status != "matched" or not result.updates:
            continue
        update = result.updates.get("prestige_metrics.openalex")
        if not update:
            continue
        stub.record["prestige_metrics"]["openalex"] = update
        stub.openalex_matched = True
        openalex_updates += 1

    return scimago_updates, openalex_updates, warnings


def validate_stub_records(stubs: list[ManifestJournalStub]) -> None:
    for stub in stubs:
        JournalRecord.model_validate(stub.record)


def render_manifest_journal_report(
    report: ManifestJournalReport,
    path: Path,
) -> None:
    lines = [
        "# Add Journals From Manifest",
        "",
        "## Summary",
        "",
        f"- Manifest journal names: {report.manifest_journal_names}",
        f"- Already present: {len(report.already_present_journals)}",
        f"- Missing: {report.missing_journals}",
        f"- Mode: {report.mode}",
        f"- SCImago matches updated: {report.scimago_updates}",
        f"- OpenAlex matches updated: {report.openalex_updates}",
        "",
        "## Journals That Would Be Added",
        "",
    ]
    if report.added_journals:
        for journal in report.added_journals:
            stub = next(item for item in report.stubs if item.journal == journal)
            inferred = ", ".join(
                f"{field}={url}" for field, url in sorted(stub.inferred_urls.items())
            ) or "-"
            source_types = ", ".join(stub.source_types) or "-"
            warnings = "; ".join(stub.warnings) or "-"
            lines.append(
                f"- {journal}: inferred URLs [{inferred}]; source types "
                f"[{source_types}]; warnings: {warnings}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## URL Fields Inferred", ""])
    lines.append("| Journal | Inferred URL fields |")
    lines.append("| --- | --- |")
    if report.stubs:
        for stub in report.stubs:
            inferred = ", ".join(
                f"{field} -> {url}" for field, url in sorted(stub.inferred_urls.items())
            ) or "-"
            lines.append(f"| {stub.journal} | {inferred} |")
    else:
        lines.append("| - | - |")
    lines.extend(["", "## Warnings", ""])
    if report.warnings:
        for warning in report.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- None")
    lines.extend(["", "## Mode", "", report.mode, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def add_journals_from_manifest(
    manifest_path: Path,
    journals_path: Path,
    out_path: Path,
    dry_run: bool = False,
    apply: bool = False,
    rebuild_index: bool = False,
    index_path: Path | None = None,
    openalex_opener: object | None = None,
    scimago_path: Path = DEFAULT_SCIMAGO_PATH,
) -> ManifestJournalReport:
    report = build_manifest_journal_report(manifest_path, journals_path)
    report.mode = "apply" if apply and not dry_run else "dry-run"

    validate_stub_records(report.stubs)
    if apply and not dry_run and report.stubs:
        scimago_updates, openalex_updates, warnings = enrich_manifest_stubs(
            report.stubs,
            scimago_path=scimago_path,
            openalex_opener=openalex_opener,
        )
        report.scimago_updates = scimago_updates
        report.openalex_updates = openalex_updates
        report.warnings.extend(warnings)
        records = load_existing_journal_records(journals_path)
        records.extend(stub.record for stub in report.stubs)
        write_journals(records, journals_path)
        validate_journal_file(journals_path)
        if rebuild_index and index_path is not None:
            rebuild_journal_index(journals_path, index_path)
            report.rebuild_index = True
    render_manifest_journal_report(report, out_path)
    return report
