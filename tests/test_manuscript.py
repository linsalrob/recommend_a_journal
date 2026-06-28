from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from journal_recommender.manuscript import (
    ManuscriptFeatures,
    validate_manuscript_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_example_manuscript_features_validate() -> None:
    manuscript = validate_manuscript_file(
        REPO_ROOT / "data/examples/microbiome_cohort_features.yaml"
    )

    assert manuscript.title
    assert manuscript.validation.computational is True
    assert manuscript.constraints.preferred_audience == "specialist_audience"


def test_manuscript_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ManuscriptFeatures.model_validate({"title": "x", "private_notes": "no"})


def test_non_mapping_manuscript_file_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")

    with pytest.raises(ValueError, match="YAML mapping"):
        validate_manuscript_file(path)


def test_no_private_manuscripts_in_examples() -> None:
    example_files = list((REPO_ROOT / "data/examples").glob("*"))

    assert example_files
    assert all(path.suffix in {".yaml", ".yml"} for path in example_files)
    assert not any(path.suffix in {".docx", ".pdf"} for path in example_files)
