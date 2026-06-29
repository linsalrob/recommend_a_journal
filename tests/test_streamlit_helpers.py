from __future__ import annotations

from pathlib import Path

import yaml

from journal_recommender.schema import JournalRecord
from journal_recommender.streamlit_helpers import (
    journal_detail,
    journal_table_rows,
    parse_manuscript_yaml_text,
    recommendation_markdown,
    recommendation_table_rows,
    score_manuscript_yaml_text,
)


def app_journal_record() -> JournalRecord:
    return JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "abbreviated_title": "Ex J",
            "publisher": "Example Publisher",
            "issn": {"print": "1234-5678", "online": "8765-4321"},
            "homepage_url": "https://example.org",
            "aims_scope_url": "https://example.org/scope",
            "author_instructions_url": "https://example.org/authors",
            "article_types": ["Research Article"],
            "scope_tags": ["microbiome", "bioinformatics"],
            "manuscript_tags": ["cohort_study", "software_tool"],
            "suitable_for": ["microbiome cohort studies"],
            "less_suitable_for": ["pure chemistry"],
            "data_policy": {
                "summary": "Data availability statement required.",
                "url": "https://example.org/data",
            },
            "code_policy": {
                "summary": "Code encouraged for computational work.",
                "url": "https://example.org/code",
            },
            "open_access": {
                "model": "hybrid",
                "apc": 1200,
                "currency": "USD",
                "url": "https://example.org/open",
            },
            "prestige_metrics": {
                "impact_factor": None,
                "cite_score": None,
                "sjr": 1.2,
                "h_index": 40,
                "quartile": "Q1",
                "metric_year": 2025,
                "metric_sources": ["curated test source"],
                "openalex": {
                    "openalex_source_id": "S123",
                    "works_count": 100,
                    "cited_by_count": 250,
                    "counts_by_year": [],
                    "openalex_h_index": 20,
                    "openalex_2yr_citation_rate": 2.5,
                    "openalex_4yr_citation_rate": 2.0,
                    "metric_year": 2026,
                    "source_url": "https://openalex.org/S123",
                    "last_checked": "2026-06-29",
                },
            },
            "editorial_notes": ["Curated note."],
            "example_papers": [],
            "source_evidence": [
                {
                    "label": "Scope",
                    "url": "https://example.org/scope",
                    "accessed": "2026-06-29",
                    "notes": "test fixture",
                }
            ],
            "last_checked": "2026-06-29",
        }
    )


def manuscript_yaml() -> str:
    return yaml.safe_dump(
        {
            "title": "Synthetic microbiome cohort",
            "abstract": "A structured synthetic feature file.",
            "central_claim": "Microbiome features stratify cohorts.",
            "field": ["microbiome"],
            "organisms": ["bacteria"],
            "sample_type": ["human gut"],
            "data_types": ["metagenomics"],
            "methods": ["bioinformatics"],
            "study_type": "cohort_study",
            "novelty_type": ["descriptive_study"],
            "mechanistic_depth": "low",
            "cohort_size": 100,
            "validation": {
                "wet_lab": False,
                "computational": True,
                "independent_dataset": False,
            },
            "code_available": True,
            "data_available": True,
            "clinical_relevance": "moderate",
            "ecological_relevance": "",
            "bioinformatics_method_novelty": "",
            "likely_article_type": "Research Article",
            "editorial_risks": [],
            "constraints": {
                "open_access_required": None,
                "max_apc": None,
                "preferred_audience": "specialist",
                "avoid_publishers": [],
            },
        },
        sort_keys=False,
    )


def test_journal_records_convert_to_display_rows() -> None:
    rows = journal_table_rows([app_journal_record()])

    assert rows[0]["journal"] == "Example Journal"
    assert rows[0]["article_types"] == "Research Article"
    assert rows[0]["scope_tags"] == "microbiome, bioinformatics"
    assert rows[0]["open_access_model"] == "hybrid"
    assert rows[0]["openalex_cited_by_count"] == 250


def test_journal_detail_contains_urls_policies_metrics_and_sources() -> None:
    detail = journal_detail(app_journal_record())

    assert detail["urls"]["homepage"] == "https://example.org"
    assert detail["data_policy_summary"] == "Data availability statement required."
    assert detail["metrics"]["openalex"]["openalex_source_id"] == "S123"
    assert detail["source_evidence"][0]["label"] == "Scope"


def test_parse_pasted_yaml_into_manuscript_features() -> None:
    manuscript = parse_manuscript_yaml_text(manuscript_yaml())

    assert manuscript.title == "Synthetic microbiome cohort"
    assert manuscript.validation.computational is True


def test_recommendation_table_rows_and_markdown_are_rendered() -> None:
    recommendations = score_manuscript_yaml_text(
        manuscript_yaml(),
        [app_journal_record()],
    )

    rows = recommendation_table_rows(recommendations)
    markdown = recommendation_markdown(recommendations)

    assert rows[0]["journal"] == "Example Journal"
    assert rows[0]["total_score"] > 0
    assert "score_scope_alignment" in rows[0]
    assert "# Journal Recommendation Report" in markdown


def test_app_helpers_do_not_write_journal_database(tmp_path: Path) -> None:
    journals_path = tmp_path / "journals.yaml"
    before = yaml.safe_dump([app_journal_record().model_dump()], sort_keys=False)
    journals_path.write_text(before, encoding="utf-8")

    recommendations = score_manuscript_yaml_text(
        manuscript_yaml(),
        [app_journal_record()],
    )
    recommendation_table_rows(recommendations)
    recommendation_markdown(recommendations)

    assert journals_path.read_text(encoding="utf-8") == before
