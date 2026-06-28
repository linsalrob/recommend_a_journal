from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from journal_recommender.schema import JournalRecord, validate_journal_file

REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL_PATH = REPO_ROOT / "data" / "journals.yaml"

REQUIRED_FIELDS = {
    "journal",
    "abbreviated_title",
    "publisher",
    "issn",
    "homepage_url",
    "aims_scope_url",
    "author_instructions_url",
    "article_types",
    "scope_tags",
    "manuscript_tags",
    "suitable_for",
    "less_suitable_for",
    "data_policy",
    "code_policy",
    "open_access",
    "prestige_metrics",
    "editorial_notes",
    "example_papers",
    "source_evidence",
    "last_checked",
}


def complete_record(journal: str) -> dict:
    return {
        "journal": journal,
        "abbreviated_title": "",
        "publisher": "",
        "issn": {"print": "", "online": ""},
        "homepage_url": "",
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
            "sjr": None,
            "h_index": None,
            "quartile": "",
            "metric_year": None,
            "metric_sources": [],
        },
        "editorial_notes": [],
        "example_papers": [],
        "source_evidence": [],
        "last_checked": "",
    }


def test_seed_journals_validate() -> None:
    journals = validate_journal_file(JOURNAL_PATH)

    assert len(journals) == 35
    assert {journal.journal for journal in journals} >= {
        "Microbiome",
        "ISME Journal",
        "Bioinformatics",
        "PLOS Computational Biology",
        "Virus Evolution",
        "PeerJ Computer Science",
        "Journal of Virology",
        "Viruses",
        "Phage",
        "Virology",
    }


def test_seed_records_keep_required_fields() -> None:
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        raw_records = yaml.safe_load(handle)

    assert isinstance(raw_records, list)
    for record in raw_records:
        assert REQUIRED_FIELDS <= set(record)
        assert set(record["issn"]) == {"print", "online"}
        assert set(record["data_policy"]) == {"summary", "url"}
        assert set(record["code_policy"]) == {"summary", "url"}
        assert set(record["open_access"]) == {"model", "apc", "currency", "url"}
        assert set(record["prestige_metrics"]) == {
            "impact_factor",
            "cite_score",
            "sjr",
            "h_index",
            "quartile",
            "metric_year",
            "metric_sources",
        }
        assert record["source_evidence"], record["journal"]


def test_missing_required_journal_name_is_invalid() -> None:
    with pytest.raises(ValidationError):
        JournalRecord.model_validate(
            {
                "homepage_url": "https://example.org",
                "issn": {"print": "", "online": ""},
            }
        )


def test_unknown_fields_are_rejected() -> None:
    valid_minimum = {
        "journal": "Example Journal",
        "unexpected": "not part of the schema",
    }

    with pytest.raises(ValidationError):
        JournalRecord.model_validate(valid_minimum)


def test_non_empty_urls_must_be_http_urls() -> None:
    with pytest.raises(ValidationError, match="URL must be empty"):
        JournalRecord.model_validate(
            {
                "journal": "Example Journal",
                "homepage_url": "example.org",
            }
        )


def test_truncated_journal_file_record_is_rejected(tmp_path: Path) -> None:
    truncated_file = tmp_path / "journals.yaml"
    truncated_file.write_text(
        yaml.safe_dump([{"journal": "Truncated Journal"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required fields"):
        validate_journal_file(truncated_file)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("data_policy", {"summary": "", "url": "example.org"}),
        ("code_policy", {"summary": "", "url": "example.org"}),
        (
            "open_access",
            {"model": "", "apc": None, "currency": "", "url": "example.org"},
        ),
        (
            "example_papers",
            [
                {
                    "title": "",
                    "doi": "",
                    "url": "example.org",
                    "reason_relevant": "",
                }
            ],
        ),
    ],
)
def test_malformed_nested_urls_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="URL must be empty"):
        JournalRecord.model_validate(
            {
                "journal": "Example Journal",
                field: value,
            }
        )


def test_valid_nested_urls_pass() -> None:
    record = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "data_policy": {"summary": "", "url": "https://example.org/data"},
            "code_policy": {"summary": "", "url": "http://example.org/code"},
            "open_access": {
                "model": "",
                "apc": None,
                "currency": "",
                "url": "https://example.org/apc",
            },
            "example_papers": [
                {
                    "title": "",
                    "doi": "",
                    "url": "https://example.org/paper",
                    "reason_relevant": "",
                }
            ],
        }
    )

    assert record.data_policy.url == "https://example.org/data"
    assert record.code_policy.url == "http://example.org/code"
    assert record.open_access.url == "https://example.org/apc"
    assert record.example_papers[0].url == "https://example.org/paper"


def test_duplicate_journal_names_are_rejected(tmp_path: Path) -> None:
    duplicate_file = tmp_path / "journals.yaml"
    duplicate_file.write_text(
        yaml.safe_dump(
            [
                complete_record("Example Journal"),
                complete_record("Example Journal"),
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate journal records"):
        validate_journal_file(duplicate_file)
