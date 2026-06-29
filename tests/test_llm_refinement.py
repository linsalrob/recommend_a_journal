from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from journal_recommender.document_extract import ExtractedManuscript
from journal_recommender.llm_refinement import (
    LLMRefinementResult,
    build_llm_refinement_input,
    build_llm_refinement_user_prompt,
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
    assert "deterministic_draft_yaml" in prompt
    assert "allowed_schema_fields" in prompt


def test_parse_llm_refinement_response_returns_result() -> None:
    payload = yaml.safe_dump(
        {
            "features": draft_features().model_dump(mode="python"),
            "confidence": {"field": "high", "study_type": "medium"},
            "evidence": {"field": ["microbiome cohort"]},
            "warnings": ["LLM-refined YAML requires user review before ranking."],
        },
        sort_keys=False,
    )

    result = parse_llm_refinement_response(payload)

    assert isinstance(result, LLMRefinementResult)
    assert result.features.title == "Synthetic microbiome cohort study"
    assert result.confidence["field"] == "high"
    assert result.evidence["field"] == ["microbiome cohort"]
    assert result.warnings


def test_refine_manuscript_features_with_fake_client(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("SYSTEM PROMPT", encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text=yaml.safe_dump(
                    {
                        "features": draft_features().model_dump(mode="python"),
                        "confidence": {"field": "high"},
                        "evidence": {"field": ["microbiome cohort"]},
                        "warnings": ["review before ranking"],
                    },
                    sort_keys=False,
                )
            )

    class FakeClient:
        responses = FakeResponses()

    result = refine_manuscript_features_with_llm(
        extracted_manuscript(),
        draft_features(),
        model="test-model",
        client=FakeClient(),
        prompt_path=prompt_path,
    )

    assert result.features.title == "Synthetic microbiome cohort study"
    assert captured["model"] == "test-model"
    assert captured["temperature"] == 0.0
    assert captured["instructions"] == "SYSTEM PROMPT"
    assert "References" not in str(captured["input"])
    assert "microbiome cohort" in str(captured["input"])


def test_refinement_response_rejects_invalid_confidence() -> None:
    payload = yaml.safe_dump(
        {
            "features": draft_features().model_dump(mode="python"),
            "confidence": {"field": "definitely"},
            "evidence": {"field": ["microbiome cohort"]},
            "warnings": [],
        }
    )

    with pytest.raises(ValueError, match="Invalid confidence levels"):
        parse_llm_refinement_response(payload)
