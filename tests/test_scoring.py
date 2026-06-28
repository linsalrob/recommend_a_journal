from __future__ import annotations

from pathlib import Path

from journal_recommender.manuscript import load_manuscript_features
from journal_recommender.schema import validate_journal_file
from journal_recommender.scoring import (
    derive_manuscript_tags,
    rank_journals_from_files,
    render_recommendation_report,
    score_journals,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNALS = REPO_ROOT / "data/journals.yaml"


def top_names(example: str, limit: int = 8) -> list[str]:
    recommendations = rank_journals_from_files(
        REPO_ROOT / f"data/examples/{example}",
        JOURNALS,
    )
    return [score.journal for score in recommendations.scores[:limit]]


def test_derive_manuscript_tags_for_software_example() -> None:
    manuscript = load_manuscript_features(
        REPO_ROOT / "data/examples/bioinformatics_tool_features.yaml"
    )

    tags = derive_manuscript_tags(manuscript)

    assert {"software_tool", "methods_paper", "benchmark", "bioinformatics"} <= tags


def test_microbiome_cohort_ranks_microbiome_journals_highly() -> None:
    names = top_names("microbiome_cohort_features.yaml")

    assert {"Microbiome", "ISME Journal", "mSystems"} & set(names[:5])
    assert "Nature" not in names[:3]
    assert "Science" not in names[:3]
    assert "Cell" not in names[:3]


def test_bioinformatics_tool_ranks_computational_journals_highly() -> None:
    names = top_names("bioinformatics_tool_features.yaml")

    assert {
        "Bioinformatics",
        "NAR Genomics and Bioinformatics",
        "GigaScience",
        "PLOS Computational Biology",
        "BMC Bioinformatics",
    } & set(names[:5])
    assert "Nature" not in names[:3]


def test_phage_genomics_ranks_virology_journals_highly() -> None:
    names = top_names("phage_genomics_features.yaml")

    assert {
        "Journal of Virology",
        "Virus Evolution",
        "Viruses",
        "Phage",
        "Microbiology Spectrum",
    } & set(names[:6])
    assert "Science" not in names[:3]


def test_score_components_are_bounded() -> None:
    manuscript = load_manuscript_features(
        REPO_ROOT / "data/examples/microbiome_cohort_features.yaml"
    )
    journals = validate_journal_file(JOURNALS)
    recommendations = score_journals(manuscript, journals)

    for score in recommendations.scores:
        assert 0 <= score.total_score <= 100
        assert all(0 <= value <= 100 for value in score.component_scores.values())
        assert score.evidence_fields_used


def test_recommendation_report_generation(tmp_path: Path) -> None:
    out = tmp_path / "recommendation.md"
    recommendations = rank_journals_from_files(
        REPO_ROOT / "data/examples/microbiome_cohort_features.yaml",
        JOURNALS,
        out,
    )
    markdown = render_recommendation_report(recommendations)

    assert out.exists()
    assert "# Journal Recommendation Report" in markdown
    assert "## Ranked Shortlist" in markdown
    assert recommendations.best_current_fit.journal in markdown
