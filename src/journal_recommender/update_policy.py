"""Central update policy for automated journal database maintenance."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

MANUAL_PROTECTED_FIELDS = frozenset(
    {
        "article_types",
        "scope_tags",
        "manuscript_tags",
        "suitable_for",
        "less_suitable_for",
        "data_policy.summary",
        "code_policy.summary",
        "open_access.model",
        "open_access.apc",
        "open_access.currency",
        "editorial_notes",
        "example_papers",
        "source_evidence",
    }
)

AUTOMATED_UPDATE_FIELDS = frozenset(
    {
        "publisher",
        "prestige_metrics.openalex",
        "prestige_metrics.sjr",
        "prestige_metrics.h_index",
        "prestige_metrics.quartile",
        "prestige_metrics.metric_year",
        "prestige_metrics.metric_sources",
        "last_checked",
        "data_raw/cache/url_cache.json",
        "data_raw/cache/hashes.json",
        "data_raw/cache/latest_update_report.json",
        "reports/journal_database_changed.md",
        "reports/metrics_audit.md",
        "data/index/journal_corpus.jsonl",
    }
)

SCIMAGO_UPDATE_FIELDS = frozenset(
    {
        "sjr",
        "h_index",
        "quartile",
        "metric_year",
        "metric_sources",
    }
)


def get_nested_field(record: dict[str, Any], field_path: str) -> Any:
    current: Any = record
    for part in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return deepcopy(current)


def protected_field_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        field_path: get_nested_field(record, field_path)
        for field_path in sorted(MANUAL_PROTECTED_FIELDS)
    }


def protected_snapshots(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(record.get("journal", "")): protected_field_snapshot(record)
        for record in records
    }


def changed_protected_fields(
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
) -> dict[str, list[str]]:
    before = protected_snapshots(before_records)
    after = protected_snapshots(after_records)
    changes: dict[str, list[str]] = {}

    for journal, before_fields in before.items():
        after_fields = after.get(journal)
        if after_fields is None:
            changes[journal] = sorted(MANUAL_PROTECTED_FIELDS)
            continue
        changed = [
            field_path
            for field_path, before_value in before_fields.items()
            if after_fields.get(field_path) != before_value
        ]
        if changed:
            changes[journal] = changed
    return changes


def count_protected_field_changes(changes: dict[str, list[str]]) -> int:
    return sum(len(fields) for fields in changes.values())


def assert_no_protected_field_changes(
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
) -> None:
    changes = changed_protected_fields(before_records, after_records)
    if changes:
        details = "; ".join(
            f"{journal}: {', '.join(fields)}"
            for journal, fields in sorted(changes.items())
        )
        raise RuntimeError(
            "Automated update attempted to change manual protected fields: "
            f"{details}"
        )
