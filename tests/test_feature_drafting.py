from __future__ import annotations

from pathlib import Path

from journal_recommender.document_extract import extract_manuscript
from journal_recommender.feature_drafting import (
    draft_features_from_extracted,
    manuscript_features_to_yaml,
)
from journal_recommender.manuscript import validate_manuscript_file
from journal_recommender.streamlit_uploads import prepare_uploaded_manuscript

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests/fixtures/manuscripts"


def test_microbiome_cohort_features_are_inferred_conservatively() -> None:
    extracted = extract_manuscript(FIXTURES / "microbiome_cohort.txt")
    features = draft_features_from_extracted(extracted)

    assert "microbiome" in features.field
    assert "shotgun metagenomics" in features.data_types
    assert "functional profiling" in features.methods
    assert features.study_type == "cohort_study"
    assert "clinical_cohort" in features.novelty_type
    assert features.validation.computational is True
    assert features.validation.wet_lab is None
    assert features.code_available is True
    assert features.data_available is True


def test_bioinformatics_tool_features_are_inferred() -> None:
    extracted = extract_manuscript(FIXTURES / "bioinformatics_tool.md")
    features = draft_features_from_extracted(extracted)

    assert "software_tool" in features.novelty_type
    assert features.study_type == "software_tool"
    assert "benchmarking" in features.methods
    assert features.code_available is True
    assert features.data_available is True
    assert "software tool" in features.likely_article_type


def test_phage_genomics_features_are_inferred() -> None:
    extracted = extract_manuscript(FIXTURES / "phage_genomics.txt")
    features = draft_features_from_extracted(extracted)

    assert "phage_biology" in features.field
    assert "viromics" in features.field
    assert "phage_genomics" in features.novelty_type
    assert features.study_type in {"descriptive_study", "environmental_survey"}
    assert (
        features.validation.computational is None or features.validation.computational
    )


def test_environmental_metagenomics_features_are_inferred() -> None:
    extracted = extract_manuscript(FIXTURES / "environmental_metagenomics.md")
    features = draft_features_from_extracted(extracted)

    assert "microbial_ecology" in features.field
    assert "metagenomics" in features.field
    assert "taxonomic profiling" in features.methods
    assert features.study_type == "environmental_survey"


def test_missing_abstract_adds_warning(tmp_path: Path) -> None:
    manuscript = tmp_path / "no_abstract.txt"
    manuscript.write_text(
        "Synthetic title\n\nIntroduction\nThis is only a body section.\n",
        encoding="utf-8",
    )

    extracted = extract_manuscript(manuscript)

    assert extracted.abstract == ""
    assert any("Abstract not detected" in warning for warning in extracted.warnings)


def test_yaml_generation_round_trips_through_schema(tmp_path: Path) -> None:
    extracted = extract_manuscript(FIXTURES / "microbiome_cohort.txt")
    features = draft_features_from_extracted(extracted)
    yaml_text = manuscript_features_to_yaml(features)
    out = tmp_path / "draft_manuscript_features.yaml"
    out.write_text(yaml_text, encoding="utf-8")

    validated = validate_manuscript_file(out)

    assert validated.title == features.title
    assert validated.validation.computational is True


def test_uploaded_manuscript_helpers_do_not_persist_to_disk(tmp_path: Path) -> None:
    before = {path for path in tmp_path.rglob("*")}
    draft = prepare_uploaded_manuscript(
        "microbiome_cohort.txt",
        (FIXTURES / "microbiome_cohort.txt").read_bytes(),
    )
    after = {path for path in tmp_path.rglob("*")}

    assert draft.extracted.filename == "microbiome_cohort.txt"
    assert draft.features.title.startswith("Synthetic gut microbiome cohort")
    assert before == after
