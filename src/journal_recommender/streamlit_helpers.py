"""Pure helper functions for the read-only Streamlit app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from journal_recommender.manuscript import ManuscriptFeatures
from journal_recommender.metrics import MetricAudit, build_metric_audit
from journal_recommender.schema import JournalRecord, validate_journal_file
from journal_recommender.scoring import (
    JournalScore,
    RecommendationSet,
    render_recommendation_report,
    score_journals,
)


def load_journals_for_app(journals_path: str | Path) -> list[JournalRecord]:
    return validate_journal_file(journals_path)


def journal_table_rows(journals: list[JournalRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for journal in journals:
        metrics = journal.prestige_metrics
        rows.append(
            {
                "journal": journal.journal,
                "publisher": journal.publisher,
                "article_types": join_values(journal.article_types),
                "scope_tags": join_values(journal.scope_tags),
                "manuscript_tags": join_values(journal.manuscript_tags),
                "open_access_model": journal.open_access.model,
                "apc": journal.open_access.apc,
                "currency": journal.open_access.currency,
                "sjr": metrics.sjr,
                "h_index": metrics.h_index,
                "quartile": metrics.quartile,
                "metric_year": metrics.metric_year,
                "openalex_cited_by_count": metrics.openalex.cited_by_count,
            }
        )
    return rows


def filter_journals(
    journals: list[JournalRecord],
    publisher: str = "",
    scope_tag: str = "",
    manuscript_tag: str = "",
    open_access_model: str = "",
    quartile: str = "",
) -> list[JournalRecord]:
    filtered = journals
    if publisher:
        filtered = [journal for journal in filtered if journal.publisher == publisher]
    if scope_tag:
        filtered = [journal for journal in filtered if scope_tag in journal.scope_tags]
    if manuscript_tag:
        filtered = [
            journal for journal in filtered if manuscript_tag in journal.manuscript_tags
        ]
    if open_access_model:
        filtered = [
            journal
            for journal in filtered
            if journal.open_access.model == open_access_model
        ]
    if quartile:
        filtered = [
            journal
            for journal in filtered
            if journal.prestige_metrics.quartile == quartile
        ]
    return filtered


def filter_options(journals: list[JournalRecord]) -> dict[str, list[str]]:
    return {
        "publishers": sorted(
            {journal.publisher for journal in journals if journal.publisher}
        ),
        "scope_tags": sorted(
            {tag for journal in journals for tag in journal.scope_tags if tag}
        ),
        "manuscript_tags": sorted(
            {tag for journal in journals for tag in journal.manuscript_tags if tag}
        ),
        "open_access_models": sorted(
            {
                journal.open_access.model
                for journal in journals
                if journal.open_access.model
            }
        ),
        "quartiles": sorted(
            {
                journal.prestige_metrics.quartile
                for journal in journals
                if journal.prestige_metrics.quartile
            }
        ),
    }


def journal_detail(journal: JournalRecord) -> dict[str, Any]:
    metrics = journal.prestige_metrics
    return {
        "journal": journal.journal,
        "urls": {
            "homepage": journal.homepage_url,
            "aims_scope": journal.aims_scope_url,
            "author_instructions": journal.author_instructions_url,
            "data_policy": journal.data_policy.url,
            "code_policy": journal.code_policy.url,
            "open_access": journal.open_access.url,
        },
        "suitable_for": journal.suitable_for,
        "less_suitable_for": journal.less_suitable_for,
        "data_policy_summary": journal.data_policy.summary,
        "code_policy_summary": journal.code_policy.summary,
        "metrics": {
            "impact_factor": metrics.impact_factor,
            "cite_score": metrics.cite_score,
            "sjr": metrics.sjr,
            "h_index": metrics.h_index,
            "quartile": metrics.quartile,
            "metric_year": metrics.metric_year,
            "metric_sources": metrics.metric_sources,
            "openalex": metrics.openalex.model_dump(),
        },
        "source_evidence": [
            evidence.model_dump() for evidence in journal.source_evidence
        ],
    }


def parse_manuscript_yaml_text(yaml_text: str) -> ManuscriptFeatures:
    raw_data = yaml.safe_load(yaml_text)
    if not isinstance(raw_data, dict):
        msg = "Manuscript feature YAML must be a mapping."
        raise ValueError(msg)
    return ManuscriptFeatures.model_validate(raw_data)


def score_manuscript_yaml_text(
    yaml_text: str,
    journals: list[JournalRecord],
) -> RecommendationSet:
    manuscript = parse_manuscript_yaml_text(yaml_text)
    return score_journals(manuscript, journals)


def recommendation_table_rows(
    recommendations: RecommendationSet,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, score in enumerate(recommendations.scores[:limit], start=1):
        row = {
            "rank": rank,
            "journal": score.journal,
            "category": score.category,
            "total_score": score.total_score,
            "matched_tags": join_values(score.matched_tags),
            "main_reason": score.main_reason,
            "main_risk": score.main_risk,
            "prestige_score_source": score.prestige_score_source,
            "key_metrics_used": join_values(score.key_metrics_used),
        }
        row.update(component_score_columns(score))
        rows.append(row)
    return rows


def component_score_columns(score: JournalScore) -> dict[str, float]:
    return {
        f"score_{name}": value for name, value in score.component_scores.items()
    }


def recommendation_markdown(recommendations: RecommendationSet) -> str:
    return render_recommendation_report(recommendations)


def build_metrics_audit_for_app(journals: list[JournalRecord]) -> MetricAudit:
    return build_metric_audit(journals)


def metrics_summary(audit: MetricAudit) -> dict[str, int]:
    return {
        "total_journals": audit.total_journals,
        "with_sjr": audit.with_sjr,
        "with_h_index": audit.with_h_index,
        "with_quartile": audit.with_quartile,
        "with_metric_year": audit.with_metric_year,
        "with_openalex_source_id": audit.with_openalex_source_id,
        "missing_scimago": len(audit.missing_scimago),
        "missing_openalex": len(audit.missing_openalex),
        "missing_or_empty_sources": len(audit.missing_or_empty_sources),
    }


def missing_metric_rows(audit: MetricAudit) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    missing_scimago = {journal.journal for journal in audit.missing_scimago}
    missing_openalex = {journal.journal for journal in audit.missing_openalex}
    for journal in audit.journals:
        rows.append(
            {
                "journal": journal.journal,
                "missing_scimago": yes_no(journal.journal in missing_scimago),
                "missing_openalex": yes_no(journal.journal in missing_openalex),
                "missing_or_empty_metric_sources": join_values(
                    audit.missing_or_empty_sources.get(journal.journal, [])
                ),
            }
        )
    return rows


def example_feature_files(examples_dir: str | Path) -> list[Path]:
    path = Path(examples_dir)
    if not path.exists():
        return []
    return sorted(path.glob("*.yaml"))


def join_values(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values if value not in (None, ""))


def yes_no(value: bool) -> str:
    return "yes" if value else "no"
