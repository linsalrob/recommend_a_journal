from __future__ import annotations

from pathlib import Path

import yaml

from journal_recommender.metrics import audit_metrics


def metric_record(journal: str, source: str = "data/source.csv") -> dict:
    return {
        "journal": journal,
        "abbreviated_title": "",
        "publisher": "",
        "issn": {"print": "", "online": ""},
        "homepage_url": "https://example.org",
        "aims_scope_url": "",
        "author_instructions_url": "",
        "article_types": [],
        "scope_tags": [],
        "manuscript_tags": [],
        "suitable_for": [],
        "less_suitable_for": [],
        "data_policy": {"summary": "", "url": ""},
        "code_policy": {"summary": "", "url": ""},
        "open_access": {"model": "", "apc": None, "currency": "", "url": ""},
        "prestige_metrics": {
            "impact_factor": None,
            "cite_score": None,
            "sjr": 1.2,
            "h_index": 10,
            "quartile": "Q1",
            "metric_year": 2025,
            "metric_sources": [f"SCImago Journal Rank 2025 dataset: {source}"],
            "openalex": {
                "openalex_source_id": "S1",
                "works_count": 10,
                "cited_by_count": 20,
                "counts_by_year": [],
                "openalex_h_index": 5,
                "openalex_2yr_citation_rate": 2.0,
                "openalex_4yr_citation_rate": 1.5,
                "metric_year": 2026,
                "source_url": "https://openalex.org/S1",
                "last_checked": "2026-06-29",
            },
        },
        "editorial_notes": [],
        "example_papers": [],
        "source_evidence": [
            {
                "label": "Homepage",
                "url": "https://example.org",
                "accessed": "2026-06-29",
                "notes": "",
            }
        ],
        "last_checked": "",
    }


def test_metric_audit_report_flags_missing_source_file(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    missing_source = tmp_path / "missing.csv"
    record = metric_record("Example Journal", str(missing_source))
    journals.write_text(yaml.safe_dump([record], sort_keys=False), encoding="utf-8")
    report = tmp_path / "metrics_audit.md"

    audit = audit_metrics(journals, report)
    markdown = report.read_text(encoding="utf-8")

    assert audit.total_journals == 1
    assert audit.with_sjr == 1
    assert "Journals with missing/empty metric source files: 1" in markdown
    assert "Example Journal" in markdown


def test_metric_audit_accepts_non_empty_source_file(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source", encoding="utf-8")
    journals = tmp_path / "journals.yaml"
    journals.write_text(
        yaml.safe_dump([metric_record("Example Journal", str(source))]),
        encoding="utf-8",
    )

    audit = audit_metrics(journals, tmp_path / "report.md")

    assert audit.missing_or_empty_sources == {}
