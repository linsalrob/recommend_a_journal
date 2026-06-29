"""Schemas and loaders for curated journal metadata."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    """Base schema that rejects misspelled or unexpected fields."""

    model_config = ConfigDict(extra="forbid")


class Issn(StrictSchema):
    print: str = ""
    online: str = ""


class Policy(StrictSchema):
    summary: str = ""
    url: str | None = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_optional_url(value)


class OpenAccess(StrictSchema):
    model: str = ""
    apc: int | float | None = None
    currency: str = ""
    url: str | None = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_optional_url(value)


class OpenAlexMetrics(StrictSchema):
    openalex_source_id: str = ""
    works_count: int | None = None
    cited_by_count: int | None = None
    counts_by_year: list[dict[str, int]] = Field(default_factory=list)
    openalex_h_index: int | None = None
    openalex_2yr_citation_rate: float | None = None
    openalex_4yr_citation_rate: float | None = None
    metric_year: int | None = None
    source_url: str | None = ""
    last_checked: str = ""

    @field_validator("source_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_optional_url(value)


class PrestigeMetrics(StrictSchema):
    impact_factor: float | None = None
    cite_score: float | None = None
    sjr: float | None = None
    h_index: int | None = None
    quartile: str = ""
    metric_year: int | None = None
    metric_sources: list[str] = Field(default_factory=list)
    openalex: OpenAlexMetrics = Field(default_factory=OpenAlexMetrics)


class ExamplePaper(StrictSchema):
    title: str = ""
    doi: str = ""
    url: str | None = ""
    reason_relevant: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_optional_url(value)


class SourceEvidence(StrictSchema):
    label: str = ""
    url: str | None = ""
    accessed: str = ""
    notes: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_optional_url(value)


class JournalRecord(StrictSchema):
    journal: str
    abbreviated_title: str = ""
    publisher: str = ""
    issn: Issn = Field(default_factory=Issn)
    homepage_url: str | None = ""
    aims_scope_url: str | None = ""
    author_instructions_url: str | None = ""
    article_types: list[str] = Field(default_factory=list)
    scope_tags: list[str] = Field(default_factory=list)
    manuscript_tags: list[str] = Field(default_factory=list)
    suitable_for: list[str] = Field(default_factory=list)
    less_suitable_for: list[str] = Field(default_factory=list)
    data_policy: Policy = Field(default_factory=Policy)
    code_policy: Policy = Field(default_factory=Policy)
    open_access: OpenAccess = Field(default_factory=OpenAccess)
    prestige_metrics: PrestigeMetrics = Field(default_factory=PrestigeMetrics)
    editorial_notes: list[str] = Field(default_factory=list)
    example_papers: list[ExamplePaper] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    last_checked: str = ""

    @field_validator("homepage_url", "aims_scope_url", "author_instructions_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_optional_url(value)


REQUIRED_TOP_LEVEL_FIELDS = frozenset(JournalRecord.model_fields)


def load_journals(path: str | Path) -> list[JournalRecord]:
    """Load and validate a journal YAML database."""

    with Path(path).open("r", encoding="utf-8") as handle:
        raw_data = yaml.safe_load(handle)

    if not isinstance(raw_data, list):
        msg = "Journal database must be a YAML list of journal records."
        raise ValueError(msg)

    return [
        JournalRecord.model_validate(require_complete_record(record, index))
        for index, record in enumerate(raw_data, start=1)
    ]


def validate_optional_url(value: str | None) -> str | None:
    """Allow empty placeholders, otherwise require an HTTP(S) URL."""

    if value and not value.startswith(("https://", "http://")):
        msg = f"URL must be empty or start with http:// or https://: {value}"
        raise ValueError(msg)
    return value


def require_complete_record(record: object, index: int) -> dict:
    """Require the explicit structured placeholder fields in each YAML record."""

    if not isinstance(record, dict):
        msg = f"Journal record {index} must be a mapping."
        raise ValueError(msg)

    missing_fields = sorted(REQUIRED_TOP_LEVEL_FIELDS - set(record))
    if missing_fields:
        journal = record.get("journal", f"record {index}")
        msg = (
            f"Journal record {journal!r} is missing required fields: "
            f"{', '.join(missing_fields)}"
        )
        raise ValueError(msg)

    return record


def validate_journal_file(path: str | Path) -> list[JournalRecord]:
    """Validate a journal YAML file and reject duplicate journal names."""

    journals = load_journals(path)
    names = [journal.journal for journal in journals]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        msg = f"Duplicate journal records found: {', '.join(duplicates)}"
        raise ValueError(msg)
    return journals
