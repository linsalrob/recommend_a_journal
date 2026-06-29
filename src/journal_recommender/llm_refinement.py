"""Optional LLM-assisted refinement for manuscript feature drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import Field, field_validator

from journal_recommender.document_extract import ExtractedManuscript
from journal_recommender.manuscript import ManuscriptFeatures, StrictSchema

REFINEMENT_SECTION_NAMES = [
    "Introduction",
    "Methods",
    "Materials and Methods",
    "Results",
    "Discussion",
    "Data Availability",
    "Code Availability",
]

MAX_SECTION_CHARS = 2500
MAX_DRAFT_CHARS = 8000
MAX_TOTAL_PROMPT_CHARS = 16000


@dataclass(frozen=True)
class LLMRefinementInput:
    title: str
    abstract: str
    selected_sections: dict[str, str]
    deterministic_draft_yaml: str
    allowed_schema_fields: list[str]
    controlled_vocabulary_hints: dict[str, list[str]]


class LLMRefinementResult(StrictSchema):
    features: ManuscriptFeatures
    confidence: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"high", "medium", "low"}
        invalid = {
            field: level for field, level in value.items() if level not in allowed
        }
        if invalid:
            raise ValueError(f"Invalid confidence levels: {sorted(invalid.items())}")
        return value


def load_llm_refinement_prompt(
    prompt_path: str | Path | None = None,
) -> str:
    path = (
        Path(prompt_path)
        if prompt_path is not None
        else Path("prompts/llm_feature_refinement.md")
    )
    return path.read_text(encoding="utf-8")


def selected_sections_for_refinement(
    extracted: ExtractedManuscript,
    max_chars_per_section: int = MAX_SECTION_CHARS,
) -> dict[str, str]:
    sections: dict[str, str] = {}
    for wanted in REFINEMENT_SECTION_NAMES:
        for name, text in extracted.sections.items():
            if name.lower() != wanted.lower() or not text.strip():
                continue
            sections[wanted] = truncate_text(text.strip(), max_chars_per_section)
            break
    return sections


def build_llm_refinement_input(
    extracted: ExtractedManuscript,
    draft_features: ManuscriptFeatures,
) -> LLMRefinementInput:
    selected_sections = selected_sections_for_refinement(extracted)
    deterministic_draft_yaml = truncate_text(
        yaml.safe_dump(draft_features.model_dump(mode="python"), sort_keys=False),
        MAX_DRAFT_CHARS,
    )
    allowed_schema_fields = list(ManuscriptFeatures.model_fields)
    controlled_vocabulary_hints = {
        "scope_tags": [
            "microbiome",
            "metagenomics",
            "microbial_genomics",
            "viromics",
            "phage_biology",
            "bioinformatics",
            "microbial_ecology",
            "clinical_microbiology",
            "computational_biology",
        ],
        "manuscript_tags": [
            "cohort_study",
            "clinical_cohort",
            "environmental_survey",
            "methods_paper",
            "software_tool",
            "database_resource",
            "genome_resource",
            "mechanistic_study",
            "descriptive_study",
            "review",
        ],
    }
    return LLMRefinementInput(
        title=extracted.title.strip(),
        abstract=extracted.abstract.strip(),
        selected_sections=selected_sections,
        deterministic_draft_yaml=deterministic_draft_yaml,
        allowed_schema_fields=allowed_schema_fields,
        controlled_vocabulary_hints=controlled_vocabulary_hints,
    )


def build_llm_refinement_user_prompt(
    extracted: ExtractedManuscript,
    draft_features: ManuscriptFeatures,
) -> str:
    request = build_llm_refinement_input(extracted, draft_features)
    payload = {
        "title": request.title,
        "abstract": request.abstract,
        "selected_sections": request.selected_sections,
        "deterministic_draft_yaml": request.deterministic_draft_yaml,
        "allowed_schema_fields": request.allowed_schema_fields,
        "controlled_vocabulary_hints": request.controlled_vocabulary_hints,
        "output_requirements": {
            "format": "strict YAML or JSON",
            "must_include": ["features", "confidence", "evidence", "warnings"],
            "must_not_include": [
                "journal rankings",
                "journal recommendations",
                "LLM prose outside the schema",
            ],
        },
    }
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return truncate_text(text, MAX_TOTAL_PROMPT_CHARS)


def refine_manuscript_features_with_llm(
    extracted: ExtractedManuscript,
    draft_features: ManuscriptFeatures,
    *,
    model: str = "gpt-4.1-mini",
    api_key: str | None = None,
    prompt_path: str | Path | None = None,
    client: object | None = None,
) -> LLMRefinementResult:
    prompt = load_llm_refinement_prompt(prompt_path)
    user_prompt = build_llm_refinement_user_prompt(extracted, draft_features)
    llm_client = client or build_openai_client(api_key=api_key)
    if not hasattr(llm_client, "responses"):
        raise RuntimeError("OpenAI client does not provide a responses API.")

    response = llm_client.responses.create(
        model=model,
        instructions=prompt,
        input=user_prompt,
        temperature=0.0,
    )
    response_text = extract_response_text(response)
    return parse_llm_refinement_response(response_text)


def build_openai_client(api_key: str | None = None) -> object:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "openai is required for LLM refinement. Install the app extras first."
        ) from exc

    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    return OpenAI(**kwargs)


def extract_response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = getattr(response, "output", None)
    if output:
        chunks: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if not content:
                continue
            for block in content:
                text = getattr(block, "text", "")
                if text:
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()
    raise ValueError("LLM response did not contain any text.")


def parse_llm_refinement_response(text: str) -> LLMRefinementResult:
    payload = parse_yaml_or_json(text)
    if not isinstance(payload, dict):
        raise ValueError("LLM refinement response must be a YAML or JSON mapping.")
    features = payload.get("features")
    if not isinstance(features, dict):
        raise ValueError("LLM refinement response must include a features mapping.")
    payload["features"] = ManuscriptFeatures.model_validate(features)
    warnings = payload.get("warnings", [])
    if warnings is None:
        payload["warnings"] = []
    return LLMRefinementResult.model_validate(payload)


def parse_yaml_or_json(text: str) -> object:
    cleaned = strip_code_fences(text).strip()
    try:
        return yaml.safe_load(cleaned)
    except yaml.YAMLError as exc:
        raise ValueError("LLM refinement response is not valid YAML/JSON.") from exc


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    match = re.match(r"^```(?:yaml|yml|json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if match:
        return match.group(1)
    return cleaned


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n[TRUNCATED]"
