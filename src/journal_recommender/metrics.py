"""Metric audit reporting for curated journal records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from journal_recommender.schema import JournalRecord, validate_journal_file
from journal_recommender.update_policy import MANUAL_PROTECTED_FIELDS


@dataclass
class MetricAudit:
    journals: list[JournalRecord]
    missing_scimago: list[JournalRecord]
    missing_openalex: list[JournalRecord]
    missing_or_empty_sources: dict[str, list[str]]
    official_metric_journals: list[JournalRecord]

    @property
    def total_journals(self) -> int:
        return len(self.journals)

    @property
    def with_sjr(self) -> int:
        return sum(
            journal.prestige_metrics.sjr is not None for journal in self.journals
        )

    @property
    def with_h_index(self) -> int:
        return sum(
            journal.prestige_metrics.h_index is not None for journal in self.journals
        )

    @property
    def with_quartile(self) -> int:
        return sum(bool(journal.prestige_metrics.quartile) for journal in self.journals)

    @property
    def with_metric_year(self) -> int:
        return sum(
            journal.prestige_metrics.metric_year is not None
            for journal in self.journals
        )

    @property
    def with_openalex_source_id(self) -> int:
        return sum(
            bool(journal.prestige_metrics.openalex.openalex_source_id)
            for journal in self.journals
        )


def audit_metrics(journals_path: Path, out_path: Path) -> MetricAudit:
    journals = validate_journal_file(journals_path)
    audit = build_metric_audit(journals)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_metric_audit(audit), encoding="utf-8")
    return audit


def build_metric_audit(journals: list[JournalRecord]) -> MetricAudit:
    missing_scimago = [
        journal for journal in journals if not has_scimago_metrics(journal)
    ]
    missing_openalex = [
        journal
        for journal in journals
        if not journal.prestige_metrics.openalex.openalex_source_id
    ]
    missing_or_empty_sources = {
        journal.journal: missing_metric_source_files(journal)
        for journal in journals
        if missing_metric_source_files(journal)
    }
    official_metric_journals = [
        journal
        for journal in journals
        if journal.prestige_metrics.impact_factor is not None
        or journal.prestige_metrics.cite_score is not None
    ]
    return MetricAudit(
        journals=journals,
        missing_scimago=missing_scimago,
        missing_openalex=missing_openalex,
        missing_or_empty_sources=missing_or_empty_sources,
        official_metric_journals=official_metric_journals,
    )


def has_scimago_metrics(journal: JournalRecord) -> bool:
    metrics = journal.prestige_metrics
    return (
        metrics.sjr is not None
        and metrics.h_index is not None
        and bool(metrics.quartile)
        and metrics.metric_year is not None
    )


def missing_metric_source_files(journal: JournalRecord) -> list[str]:
    missing: list[str] = []
    for source in journal.prestige_metrics.metric_sources:
        for candidate in source_path_candidates(source):
            path = Path(candidate)
            if not path.exists() or path.stat().st_size == 0:
                missing.append(candidate)
    return missing


def source_path_candidates(source: str) -> list[str]:
    return [
        candidate.strip("`'\"")
        for candidate in re.findall(r"(?:(?:/|\.?/)?[\w./-]+\.csv)", source)
    ]


def render_metric_audit(audit: MetricAudit) -> str:
    lines = [
        "# Metrics Audit",
        "",
        "## Summary",
        "",
        f"- Total journals: {audit.total_journals}",
        f"- Journals with SJR: {audit.with_sjr}",
        f"- Journals with h_index: {audit.with_h_index}",
        f"- Journals with quartile: {audit.with_quartile}",
        f"- Journals with metric_year: {audit.with_metric_year}",
        f"- Journals with OpenAlex source IDs: {audit.with_openalex_source_id}",
        f"- Journals missing SCImago metrics: {len(audit.missing_scimago)}",
        f"- Journals missing OpenAlex metrics: {len(audit.missing_openalex)}",
        f"- Journals with missing/empty metric source files: "
        f"{len(audit.missing_or_empty_sources)}",
        f"- Journals with official impact_factor or cite_score: "
        f"{len(audit.official_metric_journals)}",
        "- Manual protected fields changed by this run: 0",
        "",
        "## Manual Curation Protection",
        "",
        "Manual protected fields changed by this run: 0",
        "",
        "Protected fields: "
        + ", ".join(f"`{field}`" for field in sorted(MANUAL_PROTECTED_FIELDS)),
        "",
        "## Missing SCImago Metrics",
        "",
        render_name_list([journal.journal for journal in audit.missing_scimago]),
        "",
        "## Missing OpenAlex Metrics",
        "",
        render_name_list([journal.journal for journal in audit.missing_openalex]),
        "",
        "## Missing Or Empty Metric Source Files",
        "",
        render_source_file_issues(audit.missing_or_empty_sources),
        "",
        "## Official Impact Factor Or CiteScore Present",
        "",
        render_name_list(
            [journal.journal for journal in audit.official_metric_journals]
        ),
        "",
        "## All Journal Metrics",
        "",
        "| Journal | SJR | h_index | Quartile | Metric year | Metric sources | "
        "OpenAlex source | OpenAlex cited by | Impact Factor | CiteScore |",
        "| --- | ---: | ---: | --- | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for journal in audit.journals:
        metrics = journal.prestige_metrics
        openalex = metrics.openalex
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_cell(journal.journal),
                    format_optional(metrics.sjr),
                    format_optional(metrics.h_index),
                    escape_cell(metrics.quartile),
                    format_optional(metrics.metric_year),
                    escape_cell("; ".join(metrics.metric_sources)),
                    escape_cell(openalex.openalex_source_id),
                    format_optional(openalex.cited_by_count),
                    format_optional(metrics.impact_factor),
                    format_optional(metrics.cite_score),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_name_list(names: list[str]) -> str:
    if not names:
        return "No entries."
    return "\n".join(f"- {name}" for name in names)


def render_source_file_issues(issues: dict[str, list[str]]) -> str:
    if not issues:
        return "No entries."
    lines = ["| Journal | Missing or empty source file |", "| --- | --- |"]
    for journal, paths in issues.items():
        for path in paths:
            lines.append(f"| {escape_cell(journal)} | {escape_cell(path)} |")
    return "\n".join(lines)


def format_optional(value: object) -> str:
    return "" if value is None else str(value)


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
