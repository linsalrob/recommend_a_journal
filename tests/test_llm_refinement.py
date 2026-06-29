from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from journal_recommender.cli import main
from journal_recommender.document_extract import ExtractedManuscript
from journal_recommender.llm_refinement import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMRefinementError,
    LLMRefinementResult,
    build_llm_refinement_input,
    build_llm_refinement_user_prompt,
    format_llm_refinement_error,
    parse_llm_refinement_response,
    refine_manuscript_features_with_llm,
    selected_sections_for_refinement,
)
from journal_recommender.manuscript import ManuscriptFeatures


def extracted_manuscript() -> ExtractedManuscript:
    return ExtractedManuscript(
        filename="synthetic_manuscript.docx",
        file_type="docx",
        title="Synthetic microbiome cohort study",
        abstract="We studied a gut microbiome cohort.",
        sections={
            "Introduction": "Introduction text about microbiome cohorts.",
            "Methods": "Methods text with shotgun metagenomics and statistics.",
            "Results": "Results describe differential abundance.",
            "Discussion": "Discussion on ecological relevance.",
            "Data Availability": "Data are in the repository.",
            "Code Availability": "Code is on GitHub.",
            "References": "Should not be sent to the LLM.",
        },
        full_text="full text",
        warnings=[],
    )


def draft_features() -> ManuscriptFeatures:
    return ManuscriptFeatures.model_validate(
        {
            "title": "Synthetic microbiome cohort study",
            "abstract": "We studied a gut microbiome cohort.",
            "central_claim": "The cohort is stratified by microbiome profiles.",
            "field": ["microbiome"],
            "organisms": ["bacteria"],
            "sample_type": ["human gut"],
            "data_types": ["shotgun metagenomics"],
            "methods": ["functional profiling"],
            "study_type": "cohort_study",
            "novelty_type": ["clinical_cohort"],
            "mechanistic_depth": "low",
            "cohort_size": 50,
            "validation": {
                "wet_lab": None,
                "computational": True,
                "independent_dataset": None,
            },
            "code_available": True,
            "data_available": True,
            "clinical_relevance": "",
            "ecological_relevance": "",
            "bioinformatics_method_novelty": "",
            "likely_article_type": "Research Article",
            "editorial_risks": [],
            "constraints": {
                "open_access_required": None,
                "max_apc": None,
                "preferred_audience": "specialist_audience",
                "avoid_publishers": [],
            },
        }
    )


def nested_refinement_payload() -> dict[str, object]:
    return {
        "features": draft_features().model_dump(mode="python"),
        "confidence": {
            "title": "high",
            "data_types": "certain",
            "validation": {
                "wet_lab": "high",
                "computational": "medium",
                "independent_dataset": "low",
            },
            "constraints": {
                "open_access_required": "not_applicable",
                "max_apc": "likely",
                "preferred_audience": "medium",
                "avoid_publishers": "high",
            },
        },
        "evidence": {
            "data_types": "shotgun metagenomic sequencing was performed.",
            "validation": {
                "wet_lab": ["Experimental validation was performed."],
                "computational": ["The model was benchmarked."],
            },
            "constraints": {
                "open_access_required": [],
            },
        },
        "warnings": ["LLM-refined YAML requires user review before ranking."],
    }


def fake_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(output_text=yaml.safe_dump(payload, sort_keys=False))


def test_selected_sections_skip_references() -> None:
    sections = selected_sections_for_refinement(extracted_manuscript())

    assert "References" not in sections
    assert list(sections) == [
        "Introduction",
        "Methods",
        "Results",
        "Discussion",
        "Data Availability",
        "Code Availability",
    ]


def test_build_llm_refinement_prompt_limits_input_text() -> None:
    request = build_llm_refinement_input(extracted_manuscript(), draft_features())
    prompt = build_llm_refinement_user_prompt(extracted_manuscript(), draft_features())

    assert request.title == "Synthetic microbiome cohort study"
    assert "References" not in request.selected_sections
    assert "References" not in prompt
    assert "validation.wet_lab" in prompt
    assert "constraints.open_access_required" in prompt


def test_parse_llm_refinement_response_flattens_nested_shapes() -> None:
    result = parse_llm_refinement_response(yaml.safe_dump(nested_refinement_payload()))

    assert isinstance(result, LLMRefinementResult)
    assert result.features.title == "Synthetic microbiome cohort study"
    assert result.confidence["title"] == "high"
    assert result.confidence["data_types"] == "high"
    assert result.confidence["validation.wet_lab"] == "high"
    assert result.confidence["validation.computational"] == "medium"
    assert result.confidence["constraints.open_access_required"] == "low"
    assert result.evidence["data_types"] == [
        "shotgun metagenomic sequencing was performed."
    ]
    assert result.evidence["validation.wet_lab"] == [
        "Experimental validation was performed."
    ]
    assert result.evidence["validation.computational"] == [
        "The model was benchmarked."
    ]
    assert result.warnings
    assert result.raw_confidence["validation"]["wet_lab"] == "high"
    assert result.raw_evidence["validation"]["computational"] == [
        "The model was benchmarked."
    ]


def test_invalid_confidence_values_are_downgraded_with_warning() -> None:
    payload = nested_refinement_payload()
    payload["confidence"] = {"title": "unknown", "validation": {"wet_lab": "certainly"}}

    result = parse_llm_refinement_response(yaml.safe_dump(payload))

    assert result.confidence["title"] == "low"
    assert result.confidence["validation.wet_lab"] == "low"
    assert any("downgraded to low" in warning for warning in result.warnings)


def test_evidence_strings_become_lists_and_are_truncated() -> None:
    payload = nested_refinement_payload()
    payload["evidence"] = {
        "data_types": "x" * 500,
        "validation": "short note",
    }

    result = parse_llm_refinement_response(yaml.safe_dump(payload))

    assert result.evidence["data_types"] == ["x" * 297 + "..."]
    assert result.evidence["validation"] == ["short note"]
    assert any("truncated" in warning.lower() for warning in result.warnings)


def test_invalid_features_block_fails_cleanly() -> None:
    payload = nested_refinement_payload()
    payload["features"] = {"title": "x", "private_notes": "no"}

    with pytest.raises(LLMInvalidResponseError):
        parse_llm_refinement_response(yaml.safe_dump(payload))


def test_missing_api_key_raises_helpful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMAuthenticationError, match="OPENAI_API_KEY"):
        refine_manuscript_features_with_llm(extracted_manuscript(), draft_features())


def test_insufficient_quota_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeError(Exception):
        def __init__(self) -> None:
            super().__init__("Error code: 429 - quota exceeded")
            self.status_code = 429
            self.code = "insufficient_quota"
            self.body = {
                "code": "insufficient_quota",
                "message": "You exceeded your current quota.",
            }

    class FakeResponses:
        def create(self, **kwargs):
            raise FakeError()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LLMQuotaError):
        refine_manuscript_features_with_llm(
            extracted_manuscript(),
            draft_features(),
            client=FakeClient(),
        )


def test_rate_limit_error_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeError(Exception):
        def __init__(self) -> None:
            super().__init__("Error code: 429 - rate limit")
            self.status_code = 429
            self.body = {"message": "Rate limit reached."}

    class FakeResponses:
        def create(self, **kwargs):
            raise FakeError()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LLMRateLimitError):
        refine_manuscript_features_with_llm(
            extracted_manuscript(),
            draft_features(),
            client=FakeClient(),
        )


def test_authentication_error_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeError(Exception):
        def __init__(self) -> None:
            super().__init__("Incorrect API key provided")
            self.status_code = 401

    class FakeResponses:
        def create(self, **kwargs):
            raise FakeError()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LLMAuthenticationError):
        refine_manuscript_features_with_llm(
            extracted_manuscript(),
            draft_features(),
            client=FakeClient(),
        )


def test_timeout_error_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            raise TimeoutError("timed out")

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LLMRefinementError, match="network was unavailable"):
        refine_manuscript_features_with_llm(
            extracted_manuscript(),
            draft_features(),
            client=FakeClient(),
        )


def test_invalid_yaml_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            return fake_response({"not": "valid"})

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LLMInvalidResponseError):
        refine_manuscript_features_with_llm(
            extracted_manuscript(),
            draft_features(),
            client=FakeClient(),
        )


def test_format_llm_refinement_error_messages() -> None:
    message, details = format_llm_refinement_error(LLMQuotaError("quota"))

    assert "insufficient quota" in message
    assert details == "quota"


def test_cli_refine_features_llm_handles_quota_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    manuscript = tmp_path / "manuscript.txt"
    manuscript.write_text(
        "Synthetic title\n\nAbstract\nWe studied a gut microbiome cohort.\n",
        encoding="utf-8",
    )
    out = tmp_path / "refined.yaml"
    draft_out = tmp_path / "draft.yaml"

    monkeypatch.setattr(
        "journal_recommender.cli.refine_manuscript_features_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(LLMQuotaError("quota")),
    )
    exit_code = main(
        [
            "refine-features-llm",
            "--manuscript",
            str(manuscript),
            "--out",
            str(out),
            "--draft-out",
            str(draft_out),
            "--verbose",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "insufficient quota" in captured.out
    assert draft_out.exists()
    assert not out.exists()
