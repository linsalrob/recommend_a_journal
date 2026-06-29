"""Schemas and loaders for structured manuscript features."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidationFeatures(StrictSchema):
    wet_lab: bool | None = None
    computational: bool | None = None
    independent_dataset: bool | None = None


class ManuscriptConstraints(StrictSchema):
    open_access_required: bool | None = None
    max_apc: int | float | None = None
    preferred_audience: str = ""
    avoid_publishers: list[str] = Field(default_factory=list)


class ManuscriptFeatures(StrictSchema):
    title: str = ""
    abstract: str = ""
    central_claim: str = ""
    field: list[str] = Field(default_factory=list)
    organisms: list[str] = Field(default_factory=list)
    sample_type: list[str] = Field(default_factory=list)
    data_types: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    study_type: str = ""
    novelty_type: list[str] = Field(default_factory=list)
    mechanistic_depth: str = ""
    cohort_size: int | None = None
    validation: ValidationFeatures = Field(default_factory=ValidationFeatures)
    code_available: bool | None = None
    data_available: bool | None = None
    clinical_relevance: str = ""
    ecological_relevance: str = ""
    bioinformatics_method_novelty: str = ""
    likely_article_type: str = ""
    editorial_risks: list[str] = Field(default_factory=list)
    constraints: ManuscriptConstraints = Field(default_factory=ManuscriptConstraints)


def load_manuscript_features(path: str | Path) -> ManuscriptFeatures:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw_data = yaml.safe_load(handle)
    if not isinstance(raw_data, dict):
        msg = "Manuscript feature file must be a YAML mapping."
        raise ValueError(msg)
    return ManuscriptFeatures.model_validate(raw_data)


def validate_manuscript_file(path: str | Path) -> ManuscriptFeatures:
    return load_manuscript_features(path)
