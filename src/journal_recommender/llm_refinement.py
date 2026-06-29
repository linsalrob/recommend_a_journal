"""Optional LLM-assisted refinement for manuscript feature drafts."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError

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
MAX_EVIDENCE_SNIPPET_CHARS = 300

CONFIDENCE_ALIASES = {
    "certain": "high",
    "definitely": "high",
    "strong": "high",
    "high": "high",
    "likely": "medium",
    "probably": "medium",
    "moderate": "medium",
    "medium": "medium",
    "uncertain": "low",
    "unknown": "low",
    "not_applicable": "low",
    "na": "low",
    "n/a": "low",
    "low": "low",
    "false": "low",
    "no": "low",
}


@dataclass(frozen=True)
class LLMRefinementInput:
    title: str
    abstract: str
    selected_sections: dict[str, str]
    deterministic_draft_yaml: str
    allowed_schema_fields: list[str]
    controlled_vocabulary_hints: dict[str, list[str]]


class LLMRefinementError(RuntimeError):
    """Base error for optional LLM manuscript refinement."""


class LLMQuotaError(LLMRefinementError):
    pass


class LLMAuthenticationError(LLMRefinementError):
    pass


class LLMRateLimitError(LLMRefinementError):
    pass


class LLMInvalidResponseError(LLMRefinementError):
    pass


class LLMRefinementResult(StrictSchema):
    features: ManuscriptFeatures
    confidence: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    raw_confidence: dict[str, Any] = Field(default_factory=dict)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)

    def flattened_confidence(self) -> dict[str, str]:
        return flatten_confidence(self.raw_confidence or self.confidence)

    def flattened_evidence(self) -> dict[str, list[str]]:
        return flatten_evidence(self.raw_evidence or self.evidence)


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
        "response_guidance": {
            "confidence": [
                "Use flat keys where possible.",
                "Prefer dot notation for nested manuscript fields.",
                "Examples: validation.wet_lab, validation.computational, "
                "validation.independent_dataset, constraints.open_access_required, "
                "constraints.max_apc.",
            ],
            "evidence": [
                "Map each field or dot-notation field to a list of short snippets.",
                "Prefer flat keys; avoid nested dictionaries if possible.",
            ],
        },
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
        raise LLMRefinementError("OpenAI client does not provide a responses API.")

    try:
        response = llm_client.responses.create(
            model=model,
            instructions=prompt,
            input=user_prompt,
            temperature=0.0,
        )
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise classify_openai_exception(exc) from exc

    try:
        response_text = extract_response_text(response)
        return parse_llm_refinement_response(response_text)
    except LLMRefinementError:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise LLMInvalidResponseError(
            "The LLM returned a response that could not be converted into valid "
            "manuscript features. The deterministic draft is still available for "
            "editing."
        ) from exc


def build_openai_client(api_key: str | None = None) -> object:
    resolved_api_key = resolve_openai_api_key(api_key)
    if not resolved_api_key:
        raise LLMAuthenticationError(
            "LLM refinement requires OPENAI_API_KEY. Set it in your environment "
            "or continue with deterministic local extraction."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - import guard
        raise LLMRefinementError(
            "LLM refinement requires the optional openai dependency. Install the "
            "app extras and try again."
        ) from exc

    return OpenAI(api_key=resolved_api_key)


def resolve_openai_api_key(api_key: str | None = None) -> str | None:
    if api_key is not None and api_key.strip():
        return api_key.strip()
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    return env_key or None


def classify_openai_exception(exc: Exception) -> LLMRefinementError:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    code = getattr(exc, "code", None)
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    error_payload = getattr(exc, "body", None)
    if isinstance(error_payload, Mapping):
        code = code or error_payload.get("code")
        payload_message = error_payload.get("message")
        if isinstance(payload_message, str) and payload_message.strip():
            message = payload_message.strip()
            lowered = message.lower()

    if status_code == 429 and (
        code == "insufficient_quota"
        or "exceeded your current quota" in lowered
        or "insufficient quota" in lowered
    ):
        return LLMQuotaError(
            "LLM refinement is unavailable because the configured OpenAI API key "
            "has insufficient quota. Check API billing, usage limits, and project "
            "quota. You can continue with deterministic local extraction and "
            "manual YAML editing."
        )

    if status_code == 429:
        return LLMRateLimitError(
            "LLM refinement was rate-limited. Please wait and try again, or "
            "continue with deterministic local extraction and manual YAML editing."
        )

    if status_code in {401, 403} or any(
        token in lowered
        for token in [
            "invalid api key",
            "incorrect api key",
            "authentication",
            "unauthorized",
            "permission denied",
        ]
    ):
        return LLMAuthenticationError(
            "The OpenAI API key was rejected. Check that OPENAI_API_KEY is valid "
            "and belongs to the intended project."
        )

    if any(
        token in lowered
        for token in [
            "timeout",
            "timed out",
            "network",
            "connection",
            "temporarily unavailable",
            "service unavailable",
        ]
    ):
        return LLMRefinementError(
            "LLM refinement failed because the request timed out or the network "
            "was unavailable. Continue with deterministic local extraction and "
            "manual YAML editing."
        )

    return LLMRefinementError(f"LLM refinement failed: {message}")


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
    raise LLMInvalidResponseError(
        "The LLM returned a response that could not be converted into valid "
        "manuscript features. The deterministic draft is still available for "
        "editing."
    )


def parse_llm_refinement_response(text: str) -> LLMRefinementResult:
    payload = parse_yaml_or_json(text)
    if not isinstance(payload, dict):
        raise LLMInvalidResponseError(
            "The LLM returned a response that could not be converted into valid "
            "manuscript features. The deterministic draft is still available for "
            "editing."
        )

    features_data = payload.get("features")
    if not isinstance(features_data, dict):
        raise LLMInvalidResponseError(
            "The LLM returned a response that could not be converted into valid "
            "manuscript features. The deterministic draft is still available for "
            "editing."
        )

    warnings: list[str] = collect_string_warnings(payload.get("warnings"))
    confidence_tree = normalise_confidence(payload.get("confidence", {}), warnings)
    evidence_tree = normalise_evidence(payload.get("evidence", {}), warnings)

    try:
        features = ManuscriptFeatures.model_validate(features_data)
    except ValidationError as exc:
        raise LLMInvalidResponseError(
            "The LLM returned a response that could not be converted into valid "
            "manuscript features. The deterministic draft is still available for "
            "editing."
        ) from exc

    result_payload = {
        "features": features,
        "confidence": flatten_confidence(confidence_tree),
        "evidence": flatten_evidence(evidence_tree),
        "warnings": warnings,
        "raw_confidence": confidence_tree,
        "raw_evidence": evidence_tree,
    }
    return LLMRefinementResult.model_validate(result_payload)


def parse_yaml_or_json(text: str) -> object:
    cleaned = strip_code_fences(text).strip()
    try:
        return yaml.safe_load(cleaned)
    except yaml.YAMLError as exc:
        raise LLMInvalidResponseError(
            "The LLM returned a response that could not be converted into valid "
            "manuscript features. The deterministic draft is still available for "
            "editing."
        ) from exc


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    match = re.match(r"^```(?:yaml|yml|json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if match:
        return match.group(1)
    return cleaned


def normalise_confidence(
    value: Any,
    warnings: list[str] | None = None,
    path: str = "",
) -> dict[str, Any] | str:
    if isinstance(value, Mapping):
        return {
            str(key): normalise_confidence(
                subvalue,
                warnings,
                join_path(path, str(key)),
            )
            for key, subvalue in value.items()
        }
    return canonical_confidence(value, warnings, path)


def flatten_confidence(value: Any, path: str = "") -> dict[str, str]:
    flattened: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key, subvalue in value.items():
            nested_path = join_path(path, str(key))
            flattened.update(flatten_confidence(subvalue, nested_path))
        return flattened
    if path:
        flattened[path] = canonical_confidence(value, warnings=None, path=path)
    return flattened


def canonical_confidence(
    value: Any,
    warnings: list[str] | None = None,
    path: str = "",
) -> str:
    canonical_value = None
    if isinstance(value, str):
        canonical_value = CONFIDENCE_ALIASES.get(value.strip().lower())
    elif value is None:
        canonical_value = "low"
    elif isinstance(value, bool):
        canonical_value = "high" if value else "low"
    elif isinstance(value, (int, float)):
        canonical_value = (
            "high" if value >= 0.75 else "medium" if value >= 0.5 else "low"
        )

    if canonical_value is None and isinstance(value, str):
        canonical_value = "low"

    if canonical_value is None:
        canonical_value = "low"
        if warnings is not None:
            warnings.append(
                f"Confidence for {path or 'field'} had invalid value {value!r}; "
                "downgraded to low."
            )
    elif (
        isinstance(value, str)
        and value.strip().lower() not in CONFIDENCE_ALIASES
        and warnings is not None
    ):
        warnings.append(
            f"Confidence for {path or 'field'} had invalid value {value!r}; "
            "downgraded to low."
        )

    return canonical_value


def normalise_evidence(
    value: Any,
    warnings: list[str] | None = None,
    path: str = "",
) -> dict[str, Any] | list[str]:
    if isinstance(value, Mapping):
        return {
            str(key): normalise_evidence(subvalue, warnings, join_path(path, str(key)))
            for key, subvalue in value.items()
        }
    return canonical_evidence_list(value, warnings, path)


def flatten_evidence(value: Any, path: str = "") -> dict[str, list[str]]:
    flattened: dict[str, list[str]] = {}
    if isinstance(value, Mapping):
        for key, subvalue in value.items():
            nested_path = join_path(path, str(key))
            flattened.update(flatten_evidence(subvalue, nested_path))
        return flattened
    if path:
        flattened[path] = canonical_evidence_list(value, warnings=None, path=path)
    return flattened


def canonical_evidence_list(
    value: Any,
    warnings: list[str] | None = None,
    path: str = "",
) -> list[str]:
    snippets: list[str] = []
    if value is None:
        return snippets
    if isinstance(value, str):
        snippets = [value]
    elif isinstance(value, Mapping):
        nested = flatten_evidence(value, path)
        if nested:
            flattened: list[str] = []
            for entry in nested.values():
                flattened.extend(entry)
            return flattened
        return snippets
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        snippets = [item for item in value if isinstance(item, str)]
    else:
        if warnings is not None:
            warnings.append(
                f"Evidence for {path or 'field'} had an unsupported shape and "
                "was ignored."
            )
        return snippets

    cleaned: list[str] = []
    for snippet in snippets:
        text = normalise_snippet(snippet)
        if not text:
            continue
        if len(text) > MAX_EVIDENCE_SNIPPET_CHARS:
            if warnings is not None:
                warnings.append(
                    f"Evidence for {path or 'field'} exceeded "
                    f"{MAX_EVIDENCE_SNIPPET_CHARS} characters and was truncated."
                )
            text = text[: MAX_EVIDENCE_SNIPPET_CHARS - 3].rstrip() + "..."
        cleaned.append(text)
    return cleaned


def collect_string_warnings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [str(item) for item in value if isinstance(item, str) and item.strip()]
    return [str(value)]


def normalise_snippet(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def join_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def format_llm_refinement_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, LLMQuotaError):
        message = (
            "LLM refinement is unavailable because the configured OpenAI API key "
            "has insufficient quota. Check API billing, usage limits, and project "
            "quota. You can continue with deterministic local extraction and "
            "manual YAML editing."
        )
    elif isinstance(exc, LLMRateLimitError):
        message = (
            "LLM refinement was rate-limited. Please wait and try again, or "
            "continue with deterministic local extraction and manual YAML editing."
        )
    elif isinstance(exc, LLMAuthenticationError):
        if "requires OPENAI_API_KEY" in str(exc):
            message = (
                "LLM refinement requires OPENAI_API_KEY. Set it in your "
                "environment or continue with deterministic local extraction."
            )
        else:
            message = (
                "The OpenAI API key was rejected. Check that OPENAI_API_KEY is "
                "valid and belongs to the intended project."
            )
    elif isinstance(exc, LLMInvalidResponseError):
        message = (
            "The LLM returned a response that could not be converted into valid "
            "manuscript features. The deterministic draft is still available for "
            "editing."
        )
    else:
        message = (
            "LLM refinement failed. Continue with deterministic local extraction "
            "and manual YAML editing."
        )
    return message, str(exc)


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n[TRUNCATED]"
