"""Local manual-source ingestion and conservative curation suggestions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import yaml

from journal_recommender.indexing import rebuild_index
from journal_recommender.schema import validate_journal_file


@dataclass
class ManualSource:
    journal: str
    source_type: str
    url: str
    local_file: Path
    target_fields: list[str] = field(default_factory=list)


@dataclass
class ParsedManualSource:
    source: ManualSource
    status: str
    text: str = ""
    extracted_text_path: str = ""
    error: str = ""
    suggestions_generated: int = 0


ARTICLE_TYPE_PATTERNS = {
    "Research Article": r"\b(research articles?|original research|articles?)\b",
    "Review": r"\b(review articles?|reviews?)\b",
    "Brief Report": r"\b(brief reports?|brief communications?)\b",
    "Short Communication": r"\b(short communications?|short reports?)\b",
    "Method": r"\b(method|methods|methodology)\b",
    "Software": r"\b(software|application note)\b",
    "Database": r"\b(database)\b",
    "Resource": r"\b(resource|data note)\b",
}

SCOPE_KEYWORDS = {
    "microbiology": ["microbiology", "microbial"],
    "microbial_genomics": ["microbial genomics", "genomic epidemiology"],
    "microbiome": ["microbiome", "microbiota"],
    "metagenomics": ["metagenomics", "metagenomic"],
    "viromics": ["virome", "viromics", "virus"],
    "phage_biology": ["phage", "bacteriophage"],
    "bacteriophage": ["bacteriophage"],
    "microbial_ecology": ["microbial ecology", "ecology"],
    "environmental_microbiology": ["environmental microbiology", "environmental"],
    "host_microbe_interactions": ["host-microbe", "host microbe"],
    "clinical_microbiology": ["clinical microbiology", "clinical"],
    "infectious_disease": ["infectious disease", "infection"],
    "computational_biology": ["computational biology"],
    "bioinformatics": ["bioinformatics"],
    "software": ["software"],
    "methods": ["method", "methods"],
    "database": ["database"],
    "resource": ["resource"],
    "machine_learning": ["machine learning"],
    "genomics": ["genomics", "genomic"],
    "evolution": ["evolution"],
    "open_science": ["open science", "data sharing"],
}

MANUSCRIPT_KEYWORDS = {
    "specialist_audience": ["aims and scope", "journal publishes", "scope"],
    "methods_paper": ["method", "methods", "methodology"],
    "software_tool": ["software", "tool", "application note"],
    "database_resource": ["database", "resource"],
    "review": ["review"],
    "short_report": ["short communication", "brief report"],
    "phage_genomics": ["phage", "bacteriophage"],
    "virome_analysis": ["virome", "virus"],
}

SECTION_HEADING_PATTERNS = {
    "aims_scope": [
        "aims and scope",
        "aims & scope",
        "scope",
    ],
    "mission_scope": ["mission and scope", "mission & scope"],
    "about_journal": ["about the journal", "about this journal"],
    "author_instructions": [
        "information for authors",
        "instructions for authors",
        "author instructions",
    ],
    "guide_for_authors": ["guide for authors"],
    "article_types": ["article types", "types of article", "types of papers"],
    "preparing_manuscript": [
        "preparing your manuscript",
        "manuscript preparation",
    ],
    "data_policy": ["data policy"],
    "data_availability": ["data availability", "data sharing"],
    "code_availability": ["code availability", "software availability"],
    "open_access": ["open access"],
    "article_processing_charge": ["article processing charge"],
    "article_publishing_charge": ["article publishing charge"],
    "publication_fees": ["publication fees", "publishing fees"],
}

NOISE_HEADING_PATTERNS = [
    "latest articles",
    "latest issue",
    "current issue",
    "related journals",
    "most read",
    "most cited",
    "trending",
    "recommended articles",
    "recommended journals",
    "articles in press",
    "journal metrics",
    "editors",
    "editorial board",
    "submit your article",
    "sign in",
    "subscribe",
    "alerts",
    "cookie",
    "privacy policy",
    "follow us",
    "social media",
    "advertising",
]

NOISY_EVIDENCE_PHRASES = [
    "reviewers",
    "faq",
    "contact us",
    "submit manuscript",
    "submit your manuscript",
    "latest",
    "current issue",
    "article alerts",
    "author services",
]

SECTION_FIELD_MAP = {
    "article_types": [
        "article_types",
        "author_instructions",
        "guide_for_authors",
        "preparing_manuscript",
    ],
    "scope_tags": ["aims_scope", "mission_scope", "about_journal"],
    "manuscript_tags": ["aims_scope", "mission_scope", "about_journal"],
    "editorial_notes": ["aims_scope", "mission_scope", "about_journal"],
    "data_policy": ["data_policy", "data_availability", "author_instructions"],
    "code_policy": ["code_availability", "author_instructions"],
    "open_access": [
        "open_access",
        "article_processing_charge",
        "article_publishing_charge",
        "publication_fees",
    ],
}

URL_FIELDS = {"homepage_url", "aims_scope_url", "author_instructions_url"}
SUBSTANTIVE_FIELDS = {
    "article_types",
    "scope_tags",
    "manuscript_tags",
    "data_policy",
    "code_policy",
    "open_access",
    "editorial_notes",
}

SECTION_CONFIDENCE = {
    "article_types": {
        "high": {"article_types"},
        "medium": {"author_instructions", "guide_for_authors", "preparing_manuscript"},
    },
    "scope_tags": {
        "high": {"aims_scope", "mission_scope", "about_journal"},
        "medium": set(),
    },
    "manuscript_tags": {
        "high": {"aims_scope", "mission_scope", "about_journal"},
        "medium": {"article_types", "author_instructions", "guide_for_authors"},
    },
    "editorial_notes": {
        "high": {"aims_scope", "mission_scope", "about_journal"},
        "medium": set(),
    },
    "data_policy": {
        "high": {"data_policy", "data_availability"},
        "medium": {"author_instructions", "guide_for_authors", "preparing_manuscript"},
    },
    "code_policy": {
        "high": {"code_availability"},
        "medium": {"author_instructions", "guide_for_authors", "preparing_manuscript"},
    },
    "open_access": {
        "high": {
            "open_access",
            "article_processing_charge",
            "article_publishing_charge",
            "publication_fees",
        },
        "medium": set(),
    },
}


def load_manual_manifest(path: Path) -> list[ManualSource]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    sources = data.get("manual_sources", [])
    if not isinstance(sources, list):
        msg = "manual_sources must be a list."
        raise ValueError(msg)
    return [manual_source_from_mapping(source) for source in sources]


def manual_source_from_mapping(data: dict[str, Any]) -> ManualSource:
    url = str(data.get("url", ""))
    source_type = str(data.get("source_type") or infer_source_type(url))
    return ManualSource(
        journal=str(data.get("journal", "")),
        source_type=source_type,
        url=url,
        local_file=Path(str(data.get("local_file", ""))),
        target_fields=list(
            data.get("target_fields") or infer_target_fields(source_type)
        ),
    )


def parse_manual_sources(
    sources: list[ManualSource],
    text_out_dir: Path | None = None,
) -> list[ParsedManualSource]:
    parsed = []
    for source in sources:
        parsed.append(parse_manual_source(source, text_out_dir))
    return parsed


def parse_manual_source(
    source: ManualSource,
    text_out_dir: Path | None = None,
) -> ParsedManualSource:
    if not source.local_file.exists():
        return ParsedManualSource(source=source, status="missing_local_file")
    try:
        text = extract_text_from_file(source.local_file)
    except ValueError as exc:
        return ParsedManualSource(
            source=source,
            status="parsing_failed",
            error=str(exc),
        )

    if not text.strip():
        return ParsedManualSource(
            source=source,
            status="parsing_failed",
            error="Extracted text is empty.",
        )

    extracted_path = ""
    if text_out_dir is not None:
        text_out_dir.mkdir(parents=True, exist_ok=True)
        output = text_out_dir / f"{source.local_file.stem}.txt"
        output.write_text(text, encoding="utf-8")
        extracted_path = str(output)
    return ParsedManualSource(
        source=source,
        status="parsed",
        text=text,
        extracted_text_path=extracted_path,
    )


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        raw = path.read_bytes()
        return html_to_text(decode_html_bytes(raw))
    if suffix in {".txt", ".md"}:
        return normalise_whitespace(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".pdf":
        msg = "PDF parsing is not implemented; save as HTML or text first."
        raise ValueError(msg)
    msg = f"Unsupported manual source format: {suffix}"
    raise ValueError(msg)


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)</(h[1-6]|p|li|div|section|article|tr)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    lines = [normalise_whitespace(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def decode_html_bytes(raw: bytes) -> str:
    preview = raw[:500].decode("utf-8", errors="ignore")
    if "MIME-Version:" in preview and "multipart/related" in preview:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        for part in message.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="ignore") if payload else ""
    return raw.decode("utf-8", errors="ignore")


def normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_relevant_sections(text: str, source_type: str) -> dict[str, str]:
    """Split extracted text into conservative, field-relevant sections."""
    sections: dict[str, list[str]] = {}
    current_key = "full_page"
    in_noise_section = False

    for raw_line in text.splitlines():
        line = normalise_whitespace(raw_line)
        if not line:
            continue
        heading = canonical_section_heading(line)
        if heading:
            current_key = heading
            in_noise_section = False
            sections.setdefault(current_key, [])
            continue
        if is_noise_heading(line):
            in_noise_section = True
            current_key = "__noise__"
            continue
        if in_noise_section:
            next_heading = canonical_section_heading(line)
            if not next_heading:
                continue
        if is_noise_line(line):
            continue
        sections.setdefault(current_key, []).append(line)

    cleaned = {
        key: normalise_whitespace(" ".join(value))
        for key, value in sections.items()
        if key != "__noise__" and normalise_whitespace(" ".join(value))
    }
    if source_type in {"author_instructions", "guide_for_authors"}:
        cleaned = promote_full_page_author_source(cleaned)
    return cleaned


def canonical_section_heading(line: str) -> str:
    lowered = normalise_heading(line)
    if len(lowered) > 90:
        return ""
    for key, patterns in SECTION_HEADING_PATTERNS.items():
        for pattern in patterns:
            normalised_pattern = normalise_heading(pattern)
            if lowered == normalised_pattern or lowered.startswith(
                f"{normalised_pattern} "
            ):
                return key
    return ""


def normalise_heading(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_noise_heading(line: str) -> bool:
    lowered = normalise_heading(line)
    return any(pattern in lowered for pattern in NOISE_HEADING_PATTERNS)


def is_noise_line(line: str) -> bool:
    lowered = line.lower()
    if any(pattern in lowered for pattern in NOISE_HEADING_PATTERNS):
        return True
    if re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
        lowered,
    ):
        return True
    if re.search(
        r"\b\d{1,2}\s+"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b",
        lowered,
    ):
        return True
    if lowered.startswith(("home ", "menu ", "search ", "browse journals")):
        return True
    return False


def promote_full_page_author_source(sections: dict[str, str]) -> dict[str, str]:
    if "full_page" not in sections:
        return sections
    if any(
        key in sections
        for key in ["author_instructions", "guide_for_authors", "preparing_manuscript"]
    ):
        return sections
    promoted = dict(sections)
    promoted["author_instructions"] = sections["full_page"]
    return promoted


def section_text_for_field(
    sections: dict[str, str],
    field_name: str,
    source_type: str,
) -> str:
    text, _confidence, _section = section_text_with_confidence(
        sections,
        field_name,
        source_type,
    )
    return text


def section_text_with_confidence(
    sections: dict[str, str],
    field_name: str,
    source_type: str,
) -> tuple[str, str, str]:
    for section_key in SECTION_FIELD_MAP.get(field_name, []):
        if field_name == "article_types" and not can_use_article_type_section(
            section_key,
            source_type,
        ):
            continue
        text = sections.get(section_key, "")
        if is_usable_section(text):
            return text, confidence_for_section(field_name, section_key), section_key

    full_page = sections.get("full_page", "")
    if can_use_full_page_fallback(field_name, source_type, full_page):
        return full_page, "low", "full_page"
    return "", "", ""


def can_use_article_type_section(section_key: str, source_type: str) -> bool:
    if section_key == "article_types":
        return True
    return source_type in {"author_instructions", "guide_for_authors"}


def confidence_for_section(field_name: str, section_key: str) -> str:
    field_rules = SECTION_CONFIDENCE.get(field_name, {})
    if section_key in field_rules.get("high", set()):
        return "high"
    if section_key in field_rules.get("medium", set()):
        return "medium"
    return "low"


def is_usable_section(text: str) -> bool:
    return bool(text and len(text) >= 60 and is_quality_snippet(text[:220]))


def can_use_full_page_fallback(
    field_name: str,
    source_type: str,
    full_page: str,
) -> bool:
    if not is_usable_section(full_page):
        return False
    if field_name in {"scope_tags", "manuscript_tags", "editorial_notes"}:
        return source_type in {"aims_scope"} and has_scope_language(full_page)
    if field_name == "article_types":
        return source_type in {"author_instructions", "guide_for_authors"} and (
            "article type" in full_page.lower()
            or "manuscript type" in full_page.lower()
        )
    if field_name in {"data_policy", "code_policy", "open_access"}:
        return source_type in {"author_instructions", "guide_for_authors", "apc"}
    return False


def has_scope_language(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in [
            "aims and scope",
            "mission and scope",
            "about the journal",
            "journal publishes",
            "publishes research",
        ]
    )


def generate_curation_suggestions(
    parsed_sources: list[ParsedManualSource],
) -> list[dict[str, Any]]:
    suggestions = []
    for parsed in parsed_sources:
        if parsed.status != "parsed":
            continue
        suggestion = suggestion_for_parsed_source(parsed)
        parsed.suggestions_generated = count_candidate_updates(
            suggestion["candidate_updates"]
        )
        suggestions.append(suggestion)
    return suggestions


def suggestion_for_parsed_source(parsed: ParsedManualSource) -> dict[str, Any]:
    source = parsed.source
    sections = extract_relevant_sections(parsed.text, source.source_type)
    candidates: dict[str, Any] = {}
    confidence: dict[str, str] = {}
    evidence: list[dict[str, str]] = []
    warnings: list[str] = []

    if "homepage_url" in source.target_fields:
        candidates["homepage_url"] = source.url
        confidence["homepage_url"] = "high"
    if "aims_scope_url" in source.target_fields or source.source_type == "aims_scope":
        candidates["aims_scope_url"] = source.url
        confidence["aims_scope_url"] = "high"
    if (
        "author_instructions_url" in source.target_fields
        or source.source_type in {"author_instructions", "guide_for_authors"}
    ):
        candidates["author_instructions_url"] = source.url
        confidence["author_instructions_url"] = "high"

    article_text, article_confidence, article_section = section_text_with_confidence(
        sections,
        "article_types",
        source.source_type,
    )
    article_types = detect_article_types(article_text)
    article_snippet = snippet_for_terms(article_text, article_types)
    if (
        article_types
        and "article_types" in source.target_fields
        and article_snippet
        and not has_noisy_article_type_context(article_text)
    ):
        candidates["article_types"] = {"add": article_types}
        confidence["article_types"] = quality_gate_confidence(
            source,
            "article_types",
            article_confidence,
            article_snippet,
            article_section,
        )
        evidence.append({"field": "article_types", "snippet": article_snippet})
    elif article_types and "article_types" in source.target_fields:
        warnings.append("Rejected article-type evidence because it looked noisy.")
    elif (
        "article_types" in source.target_fields
        and "article_types" in sections
        and not article_text
    ):
        warnings.append("Rejected article-type evidence because it looked noisy.")
    elif (
        "article_types" in source.target_fields
        and "article type" in parsed.text.lower()
        and has_noisy_article_type_context(parsed.text)
    ):
        warnings.append("Rejected article-type evidence because it looked noisy.")
    elif "article_types" in source.target_fields and not article_text:
        warnings.append("No relevant article-type or author-instruction section found.")

    scope_text, scope_confidence, _section = section_text_with_confidence(
        sections,
        "scope_tags",
        source.source_type,
    )
    scope_tags = detect_tags(scope_text, SCOPE_KEYWORDS)
    scope_snippet = snippet_for_terms(scope_text, scope_tags)
    if scope_tags and "scope_tags" in source.target_fields:
        candidates["scope_tags"] = {"add": scope_tags}
        confidence["scope_tags"] = quality_gate_confidence(
            source,
            "scope_tags",
            scope_confidence,
            scope_snippet,
            _section,
        )
        if scope_snippet:
            evidence.append({"field": "scope_tags", "snippet": scope_snippet})
    elif "scope_tags" in source.target_fields and not scope_text:
        warnings.append("No clean aims/scope/about section found; scope tags omitted.")

    manuscript_text, manuscript_confidence, manuscript_section = (
        section_text_with_confidence(
            sections,
            "manuscript_tags",
            source.source_type,
        )
    )
    manuscript_tags = detect_tags(manuscript_text, MANUSCRIPT_KEYWORDS)
    manuscript_snippet = snippet_for_terms(manuscript_text, manuscript_tags)
    if manuscript_tags and "manuscript_tags" in source.target_fields:
        candidates["manuscript_tags"] = {"add": manuscript_tags}
        confidence["manuscript_tags"] = quality_gate_confidence(
            source,
            "manuscript_tags",
            manuscript_confidence,
            manuscript_snippet,
            manuscript_section,
        )

    if "data_policy" in source.target_fields:
        policy_text, policy_confidence, _section = section_text_with_confidence(
            sections,
            "data_policy",
            source.source_type,
        )
        summary = policy_summary(
            policy_text,
            [
                "data availability",
                "data availability statement",
                "data sharing",
                "data and code deposition",
            ],
        )
        if summary:
            candidates["data_policy"] = {"summary": summary, "url": source.url}
            confidence["data_policy"] = quality_gate_confidence(
                source,
                "data_policy",
                policy_confidence,
                summary,
                _section,
            )
            evidence.append({"field": "data_policy", "snippet": summary})
        elif policy_text:
            warnings.append("Rejected data-policy candidate because summary was empty.")
    if "code_policy" in source.target_fields:
        policy_text, policy_confidence, _section = section_text_with_confidence(
            sections,
            "code_policy",
            source.source_type,
        )
        summary = policy_summary(
            policy_text,
            [
                "code availability",
                "software availability",
                "software and code",
                "source code",
                "data and code deposition",
            ],
        )
        if summary:
            candidates["code_policy"] = {"summary": summary, "url": source.url}
            confidence["code_policy"] = quality_gate_confidence(
                source,
                "code_policy",
                policy_confidence,
                summary,
                _section,
            )
            evidence.append({"field": "code_policy", "snippet": summary})
        elif policy_text:
            warnings.append("Rejected code-policy candidate because summary was empty.")
    if "open_access" in source.target_fields or source.source_type in {
        "apc",
        "open_access",
    }:
        oa_text, oa_confidence, _section = section_text_with_confidence(
            sections,
            "open_access",
            source.source_type,
        )
        if oa_text:
            candidates["open_access"] = open_access_candidate(source, oa_text)
            confidence["open_access"] = quality_gate_confidence(
                source,
                "open_access",
                oa_confidence,
                snippet_for_terms(
                    oa_text,
                    ["open access", "article processing charge", "publication fees"],
                ),
                _section,
            )
        if not oa_text or candidates.get("open_access", {}).get("apc") is None:
            warnings.append("APC amount not extracted confidently.")

    if "editorial_notes" in source.target_fields:
        note = editorial_note_candidate(
            source,
            scope_text,
            scope_tags,
            scope_confidence,
        )
        if note:
            candidates["editorial_notes"] = {"add": [note]}
            confidence["editorial_notes"] = "high"

    status = suggestion_status(candidates, confidence, warnings, source.target_fields)

    return {
        "journal": source.journal,
        "source_type": source.source_type,
        "status": status,
        "source_url": source.url,
        "local_file": str(source.local_file),
        "extracted_text_path": parsed.extracted_text_path,
        "candidate_updates": candidates,
        "confidence": confidence,
        "evidence": evidence[:6],
        "warnings": warnings,
    }


def detect_article_types(text: str) -> list[str]:
    lowered = text.lower()
    article_types = [
        label
        for label, pattern in ARTICLE_TYPE_PATTERNS.items()
        if re.search(pattern, lowered)
    ]
    return sorted(set(article_types))


def detect_tags(text: str, vocabulary: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    tags = [
        tag
        for tag, terms in vocabulary.items()
        if any(term in lowered for term in terms)
    ]
    return sorted(set(tags))


def policy_summary(text: str, terms: list[str]) -> str:
    return snippet_for_terms(text, terms)


def open_access_candidate(source: ManualSource, text: str) -> dict[str, Any]:
    lowered = text.lower()
    model = ""
    if "open access" in lowered:
        model = "open_access"
    apc = parse_apc(text)
    return {
        "model": model,
        "apc": apc[0] if apc else None,
        "currency": apc[1] if apc else "",
        "url": source.url,
    }


def parse_apc(text: str) -> tuple[int | float, str] | None:
    matches = []
    for pattern, currency in [
        (r"(?:USD|US\$|\$)\s?([0-9][0-9,]*(?:\.\d+)?)", "USD"),
        (r"(?:EUR|€)\s?([0-9][0-9,]*(?:\.\d+)?)", "EUR"),
        (r"(?:GBP|£)\s?([0-9][0-9,]*(?:\.\d+)?)", "GBP"),
    ]:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            amount = float(match.group(1).replace(",", ""))
            matches.append((int(amount) if amount.is_integer() else amount, currency))
    unique = sorted(set(matches))
    return unique[0] if len(unique) == 1 else None


def editorial_note_candidate(
    source: ManualSource,
    scope_text: str,
    scope_tags: list[str],
    scope_confidence: str,
) -> str:
    if (
        source.source_type in {"homepage_or_scope", "aims_scope"}
        and scope_confidence == "high"
        and is_usable_section(scope_text)
        and scope_tags
    ):
        readable_tags = ", ".join(tag.replace("_", " ") for tag in scope_tags[:4])
        return f"Manual source indicates journal scope includes {readable_tags}."
    return ""


def add_evidence(
    evidence: list[dict[str, str]],
    field: str,
    text: str,
    terms: list[str],
) -> None:
    snippet = snippet_for_terms(text, terms)
    if snippet:
        evidence.append({"field": field, "snippet": snippet})


def quality_gate_confidence(
    source: ManualSource,
    field_name: str,
    initial_confidence: str,
    evidence_snippet: str,
    section_key: str,
) -> str:
    if field_name in {"article_types", "scope_tags", "manuscript_tags"}:
        if not evidence_snippet or looks_like_noise_snippet(evidence_snippet):
            return "low"
    if field_name in {"data_policy", "code_policy"} and not evidence_snippet:
        return "low"
    if field_name == "article_types" and section_key != "article_types":
        if source.source_type == "homepage_or_scope":
            return "low"
        return initial_confidence
    if is_likely_publisher_wide_source(source) and field_name in SUBSTANTIVE_FIELDS:
        return "low"
    return initial_confidence


def has_noisy_article_type_context(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in NOISY_EVIDENCE_PHRASES):
        return True
    if re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
        r"\d{1,2},?\s+\d{4}\b",
        lowered,
    ):
        return True
    return bool(
        re.search(
            r"\b\d{1,2}\s+"
            r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
            r"\d{4}\b",
            lowered,
        )
    )


def is_likely_publisher_wide_source(source: ManualSource) -> bool:
    path_name = source.local_file.name.lower()
    url = source.url.lower()
    return any(
        marker in path_name or marker in url
        for marker in [
            "asm_authors",
            "asm_publishing_fees",
            "publishing-fees",
            "author-center",
            "for-authors",
        ]
    )


def suggestion_status(
    candidates: dict[str, Any],
    confidence: dict[str, str],
    warnings: list[str],
    target_fields: list[str],
) -> str:
    if not candidates:
        if any("rejected" in warning.lower() for warning in warnings):
            return "rejected_noise"
        if any(
            field in target_fields
            for field in ["scope_tags", "article_types", "data_policy", "code_policy"]
        ):
            return "missing_relevant_section"
        return "parsed_no_updates"
    if any("rejected" in warning.lower() for warning in warnings):
        if not any(field in SUBSTANTIVE_FIELDS for field in candidates):
            return "rejected_noise"
    if any(
        "omitted" in warning.lower() or "no relevant" in warning.lower()
        for warning in warnings
    ):
        if not any(
            field in SUBSTANTIVE_FIELDS and level in {"high", "medium"}
            for field, level in confidence.items()
        ):
            return "missing_relevant_section"
    if any(
        field in SUBSTANTIVE_FIELDS and level == "low"
        for field, level in confidence.items()
    ):
        return "low_confidence"
    high_substantive = any(
        field in SUBSTANTIVE_FIELDS and level == "high"
        for field, level in confidence.items()
    )
    if high_substantive:
        return "ready_for_review"
    if candidates and all(field in URL_FIELDS for field in candidates):
        return "ready_for_review"
    return "ready_for_review"


def snippet_for_terms(text: str, terms: list[str], limit: int = 180) -> str:
    flat = normalise_whitespace(text)
    lowered = flat.lower()
    for term in terms:
        index = lowered.find(term.lower())
        if index == -1:
            continue
        start = max(0, index - 70)
        end = min(len(flat), index + limit)
        snippet = flat[start:end].strip()
        return snippet if is_quality_snippet(snippet) else ""
    return ""


def is_quality_snippet(snippet: str) -> bool:
    if len(snippet) < 20:
        return False
    if looks_like_noise_snippet(snippet):
        return False
    encoded_markers = snippet.count("=20") + snippet.count("=E2") + snippet.count("=0")
    if encoded_markers:
        return False
    alnum = sum(char.isalnum() for char in snippet)
    return (alnum / max(len(snippet), 1)) > 0.45


def looks_like_noise_snippet(snippet: str) -> bool:
    lowered = snippet.lower()
    noise_hits = sum(
        1
        for phrase in NOISE_HEADING_PATTERNS
        if phrase in normalise_heading(lowered)
    )
    if noise_hits >= 2:
        return True
    return any(
        phrase in lowered
        for phrase in [
            "accept all cookies",
            "skip to main content",
            "create account",
            "view all journals",
        ]
    )


def count_candidate_updates(candidates: dict[str, Any]) -> int:
    total = 0
    for value in candidates.values():
        if isinstance(value, dict) and "add" in value:
            total += len(value["add"])
        elif value:
            total += 1
    return total


def write_suggestions(suggestions: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(suggestions, handle, sort_keys=False, allow_unicode=True)


def write_review_report(
    suggestions: list[dict[str, Any]],
    parsed_sources: list[ParsedManualSource],
    path: Path,
    journals_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    high_count = sum(
        1
        for suggestion in suggestions
        if any(level == "high" for level in suggestion.get("confidence", {}).values())
    )
    low_count = sum(
        1
        for suggestion in suggestions
        if any(level == "low" for level in suggestion.get("confidence", {}).values())
    )
    rejected_count = sum(
        1
        for suggestion in suggestions
        if suggestion.get("status")
        in {"rejected_noise", "missing_relevant_section", "parsed_no_updates"}
    )
    no_update_count = sum(
        1
        for suggestion in suggestions
        if suggestion.get("status") == "parsed_no_updates"
    )
    parsed_count = sum(1 for item in parsed_sources if item.status == "parsed")
    url_only = [
        suggestion for suggestion in suggestions if is_url_only_suggestion(suggestion)
    ]
    substantive_high = [
        suggestion
        for suggestion in suggestions
        if not is_url_only_suggestion(suggestion)
        and any(
            field in SUBSTANTIVE_FIELDS and level == "high"
            for field, level in suggestion.get("confidence", {}).items()
        )
    ]
    low_or_noisy = [
        suggestion
        for suggestion in suggestions
        if suggestion.get("status") in {"low_confidence", "rejected_noise"}
    ]
    missing_sections = [
        suggestion
        for suggestion in suggestions
        if suggestion.get("status") == "missing_relevant_section"
    ]
    lines = [
        "# Manual Curation Review",
        "",
        "## Summary",
        "",
        f"- Total manual sources parsed: {parsed_count}",
        f"- High-confidence suggestions: {high_count}",
        f"- Low-confidence suggestions: {low_count}",
        f"- Rejected/noisy or missing-section suggestions: {rejected_count}",
        f"- Sources with no useful updates: {no_update_count}",
        "",
    ]
    append_review_section(lines, "URL-only Suggestions", url_only)
    append_review_section(
        lines,
        "Substantive High-confidence Suggestions",
        substantive_high,
    )
    append_review_section(lines, "Low-confidence Or Noisy Suggestions", low_or_noisy)
    append_review_section(lines, "Missing Relevant Sections", missing_sections)
    if journals_path is not None:
        append_missing_field_summary(lines, journals_path)
    safe_to_apply, reason = safe_to_apply_decision(suggestions)
    lines.extend(
        [
            "",
            "## Recommended Action",
            "",
            reason,
            "",
            "## Machine-readable Recommendation",
            "",
            "```yaml",
            *yaml.safe_dump(
                {"safe_to_apply": safe_to_apply, "reason": reason},
                sort_keys=False,
            ).strip().splitlines(),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def append_review_section(
    lines: list[str],
    title: str,
    suggestions: list[dict[str, Any]],
) -> None:
    lines.extend(
        [
            f"## {title}",
            "",
            "| Journal | Source type | Local file | Status | "
            "High-confidence fields | Low-confidence fields | Warnings |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if not suggestions:
        lines.append("| - | - | - | - | - | - | - |")
        lines.append("")
        return
    for suggestion in suggestions:
        confidence = suggestion.get("confidence", {})
        high_fields = ", ".join(
            field for field, level in confidence.items() if level == "high"
        )
        low_fields = ", ".join(
            field for field, level in confidence.items() if level == "low"
        )
        warnings = "; ".join(suggestion.get("warnings", []))
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(suggestion.get("journal", "")),
                    markdown_cell(suggestion.get("source_type", "")),
                    markdown_cell(suggestion.get("local_file", "")),
                    markdown_cell(suggestion.get("status", "")),
                    markdown_cell(high_fields or "-"),
                    markdown_cell(low_fields or "-"),
                    markdown_cell(warnings or "-"),
                ]
            )
            + " |"
        )
    lines.append("")


def is_url_only_suggestion(suggestion: dict[str, Any]) -> bool:
    candidates = suggestion.get("candidate_updates", {})
    return bool(candidates) and all(field in URL_FIELDS for field in candidates)


def recommended_action(suggestions: list[dict[str, Any]]) -> str:
    return safe_to_apply_decision(suggestions)[1]


def safe_to_apply_decision(suggestions: list[dict[str, Any]]) -> tuple[bool, str]:
    risky = [
        suggestion
        for suggestion in suggestions
        if suggestion.get("status") in {"low_confidence", "rejected_noise"}
    ]
    substantive = [
        suggestion
        for suggestion in suggestions
        if not is_url_only_suggestion(suggestion)
        and any(
            field in SUBSTANTIVE_FIELDS
            for field in suggestion.get("confidence", {})
        )
    ]
    if risky or substantive:
        return False, (
            "More review is needed before running `--apply`; inspect the dry-run "
            "report and manually check substantive suggestions first."
        )
    return True, "It is safe to run `--apply` for URL-only suggestions."


def append_missing_field_summary(lines: list[str], journals_path: Path) -> None:
    with journals_path.open("r", encoding="utf-8") as handle:
        records = yaml.safe_load(handle) or []
    lines.extend(
        [
            "## Missing Field Summary",
            "",
            "| Journal | Missing useful fields |",
            "| --- | --- |",
        ]
    )
    for record in records:
        missing = missing_useful_fields(record)
        if missing:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(record.get("journal", "")),
                        markdown_cell(", ".join(missing)),
                    ]
                )
                + " |"
            )
    lines.append("")


def missing_useful_fields(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not record.get("scope_tags"):
        missing.append("scope_tags")
    if not record.get("article_types"):
        missing.append("article_types")
    if not record.get("data_policy", {}).get("summary"):
        missing.append("data_policy.summary")
    if not record.get("code_policy", {}).get("summary"):
        missing.append("code_policy.summary")
    if not record.get("open_access", {}).get("url"):
        missing.append("open_access.url")
    return missing


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def apply_suggestions_to_journals(
    suggestions: list[dict[str, Any]],
    journals_path: Path,
    include_low_confidence: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    with journals_path.open("r", encoding="utf-8") as handle:
        records = yaml.safe_load(handle)
    by_journal = {record["journal"]: record for record in records}
    applied = 0
    skipped_unknown: list[str] = []

    for suggestion in suggestions:
        record = by_journal.get(suggestion["journal"])
        if record is None:
            skipped_unknown.append(suggestion["journal"])
            continue
        updates = filter_updates_by_confidence(
            suggestion.get("candidate_updates", {}),
            suggestion.get("confidence", {}),
            include_low_confidence=include_low_confidence,
        )
        before = applied
        applied += apply_candidate_updates(record, updates)
        if applied > before and not dry_run:
            add_source_evidence(record, suggestion)

    if not dry_run:
        with journals_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(records, handle, sort_keys=False, allow_unicode=True)

        validate_journal_file(journals_path)
    return {
        "applied": applied,
        "skipped_unknown": sorted(set(skipped_unknown)),
        "dry_run": dry_run,
    }


def build_dry_run_report(
    suggestions: list[dict[str, Any]],
    journals_path: Path,
    report_path: Path,
    include_low_confidence: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    with journals_path.open("r", encoding="utf-8") as handle:
        records = yaml.safe_load(handle)
    by_journal = {record["journal"]: record for record in records}
    rows: list[dict[str, Any]] = []
    skipped_unknown: list[str] = []
    skipped_low_rows: list[dict[str, Any]] = []

    for suggestion in suggestions:
        record = by_journal.get(suggestion["journal"])
        if record is None:
            skipped_unknown.append(suggestion["journal"])
            continue
        updates = suggestion.get("candidate_updates", {})
        confidence = suggestion.get("confidence", {})
        for field_name, value in updates.items():
            if not confidence_allowed(
                confidence.get(field_name, ""),
                include_low_confidence,
            ):
                skipped_low_rows.extend(
                    collect_skipped_low_rows(record, field_name, value, suggestion)
                )
        allowed_updates = filter_updates_by_confidence(
            updates,
            confidence,
            include_low_confidence=include_low_confidence,
        )
        rows.extend(
            collect_dry_run_rows(record, allowed_updates, confidence, suggestion)
        )

    visible_rows = [
        row
        for row in [*rows, *skipped_low_rows]
        if verbose or row["action"] != "identical_existing"
    ]
    change_count = sum(1 for row in rows if row["action"] == "would_change")
    identical_count = sum(1 for row in rows if row["action"] == "identical_existing")
    conflict_count = sum(1 for row in rows if row["action"] == "preserve_conflict")
    skipped_low_count = len(skipped_low_rows)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_dry_run_markdown(
        report_path,
        suggestions_considered=len(suggestions),
        would_change=change_count,
        identical=identical_count,
        skipped_low=skipped_low_count,
        skipped_unknown=sorted(set(skipped_unknown)),
        preserved_conflicts=conflict_count,
        rows=visible_rows,
        verbose=verbose,
    )
    return {
        "would_apply": change_count,
        "would_change": change_count,
        "identical_existing": identical_count,
        "skipped_low_confidence": skipped_low_count,
        "skipped_unknown": sorted(set(skipped_unknown)),
        "preserved_existing": conflict_count,
        "report": str(report_path),
    }


def confidence_allowed(confidence: str, include_low_confidence: bool) -> bool:
    if include_low_confidence:
        return confidence in {"high", "medium", "low"}
    return confidence == "high"


def collect_dry_run_rows(
    record: dict[str, Any],
    updates: dict[str, Any],
    confidence: dict[str, str],
    suggestion: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, value in updates.items():
        if field_name in {
            "article_types",
            "scope_tags",
            "manuscript_tags",
            "editorial_notes",
        }:
            existing = record.setdefault(field_name, [])
            for proposed in value.get("add", []):
                action = (
                    "identical_existing" if proposed in existing else "would_change"
                )
                rows.append(
                    dry_run_row(
                        suggestion,
                        field_name,
                        action,
                        existing,
                        proposed,
                        confidence,
                    )
                )
        elif field_name in {"data_policy", "code_policy", "open_access"}:
            target = record.get(field_name, {})
            for key, proposed in value.items():
                if proposed in {"", None}:
                    continue
                existing = target.get(key)
                action = action_for_scalar(existing, proposed)
                rows.append(
                    dry_run_row(
                        suggestion,
                        f"{field_name}.{key}",
                        action,
                        existing,
                        proposed,
                        confidence,
                        confidence_field=field_name,
                    )
                )
        elif field_name in record and value:
            existing = record.get(field_name)
            action = action_for_scalar(existing, value)
            rows.append(
                dry_run_row(
                    suggestion,
                    field_name,
                    action,
                    existing,
                    value,
                    confidence,
                )
            )
    return rows


def collect_skipped_low_rows(
    record: dict[str, Any],
    field_name: str,
    value: Any,
    suggestion: dict[str, Any],
) -> list[dict[str, Any]]:
    confidence = suggestion.get("confidence", {})
    rows: list[dict[str, Any]] = []
    if field_name in {
        "article_types",
        "scope_tags",
        "manuscript_tags",
        "editorial_notes",
    }:
        existing = record.get(field_name, [])
        for proposed in value.get("add", []):
            rows.append(
                dry_run_row(
                    suggestion,
                    field_name,
                    "skipped_low_confidence",
                    existing,
                    proposed,
                    confidence,
                )
            )
    elif field_name in {"data_policy", "code_policy", "open_access"}:
        target = record.get(field_name, {})
        for key, proposed in value.items():
            if proposed in {"", None}:
                continue
            rows.append(
                dry_run_row(
                    suggestion,
                    f"{field_name}.{key}",
                    "skipped_low_confidence",
                    target.get(key),
                    proposed,
                    confidence,
                    confidence_field=field_name,
                )
            )
    elif field_name in record and value:
        rows.append(
            dry_run_row(
                suggestion,
                field_name,
                "skipped_low_confidence",
                record.get(field_name),
                value,
                confidence,
            )
        )
    return rows


def action_for_scalar(existing: Any, proposed: Any) -> str:
    if is_empty_value(existing):
        return "would_change"
    if normalise_compare_value(existing) == normalise_compare_value(proposed):
        return "identical_existing"
    return "preserve_conflict"


def normalise_compare_value(value: Any) -> str:
    return normalise_whitespace(str(value or ""))


def dry_run_row(
    suggestion: dict[str, Any],
    field_name: str,
    action: str,
    existing: Any,
    proposed: Any,
    confidence: dict[str, str],
    confidence_field: str | None = None,
) -> dict[str, Any]:
    return {
        "journal": suggestion.get("journal", ""),
        "field": field_name,
        "action": action,
        "existing": existing,
        "proposed": proposed,
        "confidence": confidence.get(confidence_field or field_name, ""),
        "source": suggestion.get("source_url", ""),
    }


def write_dry_run_markdown(
    path: Path,
    suggestions_considered: int,
    would_change: int,
    identical: int,
    skipped_low: int,
    skipped_unknown: list[str],
    preserved_conflicts: int,
    rows: list[dict[str, Any]],
    verbose: bool = False,
) -> None:
    lines = [
        "# Manual Apply Dry Run",
        "",
        "## Summary",
        "",
        f"- Suggestions considered: {suggestions_considered}",
        f"- Fields that would actually change: {would_change}",
        f"- Fields already identical: {identical}",
        "- Fields skipped because existing curated values are non-empty: "
        f"{preserved_conflicts}",
        f"- Fields skipped because confidence is too low: {skipped_low}",
        f"- Unknown journals skipped: {len(skipped_unknown)}",
        f"- Verbose identical rows shown: {str(verbose).lower()}",
        "",
    ]
    if skipped_unknown:
        lines.extend(["Unknown journals: " + ", ".join(skipped_unknown), ""])
    lines.extend(
        [
            "## Proposed Changes",
            "",
            "| Journal | Field | Action | Existing value | Proposed value | "
            "Confidence | Source |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(row["journal"]),
                    markdown_cell(row["field"]),
                    markdown_cell(row["action"]),
                    markdown_cell(short_value(row["existing"])),
                    markdown_cell(short_value(row["proposed"])),
                    markdown_cell(row["confidence"]),
                    markdown_cell(row["source"]),
                ]
            )
            + " |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def short_value(value: Any, limit: int = 120) -> str:
    if is_empty_value(value):
        return ""
    text = normalise_whitespace(str(value))
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == []


def filter_updates_by_confidence(
    updates: dict[str, Any],
    confidence: dict[str, str],
    include_low_confidence: bool,
) -> dict[str, Any]:
    allowed = {"high", "medium", "low"} if include_low_confidence else {"high"}
    return {
        field_name: value
        for field_name, value in updates.items()
        if confidence.get(field_name) in allowed
    }


def apply_candidate_updates(record: dict[str, Any], updates: dict[str, Any]) -> int:
    applied = 0
    for field_name, value in updates.items():
        if field_name in {
            "article_types",
            "scope_tags",
            "manuscript_tags",
            "editorial_notes",
        }:
            applied += append_unique(
                record.setdefault(field_name, []),
                value.get("add", []),
            )
        elif field_name in {"data_policy", "code_policy"}:
            target = record.setdefault(field_name, {"summary": "", "url": ""})
            for key in ["summary", "url"]:
                if not target.get(key) and value.get(key):
                    target[key] = value[key]
                    applied += 1
        elif field_name == "open_access":
            target = record.setdefault(
                "open_access",
                {"model": "", "apc": None, "currency": "", "url": ""},
            )
            for key in ["model", "url", "currency"]:
                if not target.get(key) and value.get(key):
                    target[key] = value[key]
                    applied += 1
            if target.get("apc") is None and value.get("apc") is not None:
                target["apc"] = value["apc"]
                applied += 1
        elif field_name in record and not record.get(field_name) and value:
            record[field_name] = value
            applied += 1
    return applied


def append_unique(target: list[Any], values: list[Any]) -> int:
    applied = 0
    for value in values:
        if value and value not in target:
            target.append(value)
            applied += 1
    return applied


def add_source_evidence(record: dict[str, Any], suggestion: dict[str, Any]) -> None:
    source_url = suggestion.get("source_url", "")
    if not source_url:
        return
    entry = {
        "label": f"Manual source: {suggestion.get('source_type', '')}",
        "url": source_url,
        "accessed": "2026-06-29",
        "notes": f"Parsed from local file {suggestion.get('local_file', '')}.",
    }
    evidence = record.setdefault("source_evidence", [])
    if not any(
        item.get("url") == source_url and item.get("label") == entry["label"]
        for item in evidence
    ):
        evidence.append(entry)


def infer_source_type(url: str) -> str:
    lowered = url.lower()
    if any(
        token in lowered for token in ["authors", "instructions", "guide-for-authors"]
    ):
        return "author_instructions"
    if any(token in lowered for token in ["aims-and-scope", "about", "scope"]):
        return "aims_scope"
    if "data-policy" in lowered:
        return "data_policy"
    if "code" in lowered:
        return "code_policy"
    if any(
        token in lowered
        for token in [
            "publishing-fees",
            "pricing",
            "apc",
            "article-processing-charge",
            "open-access-options",
        ]
    ):
        return "apc"
    return "homepage_or_scope"


def infer_target_fields(source_type: str) -> list[str]:
    if source_type in {"author_instructions", "guide_for_authors"}:
        return [
            "author_instructions_url",
            "article_types",
            "data_policy",
            "code_policy",
        ]
    if source_type == "aims_scope":
        return ["aims_scope_url", "scope_tags", "suitable_for", "less_suitable_for"]
    if source_type == "data_policy":
        return ["data_policy"]
    if source_type == "code_policy":
        return ["code_policy"]
    if source_type in {"apc", "open_access"}:
        return ["open_access"]
    return [
        "homepage_url",
        "aims_scope_url",
        "article_types",
        "scope_tags",
        "manuscript_tags",
        "suitable_for",
        "less_suitable_for",
        "editorial_notes",
    ]


def process_manual_sources(
    manifest_path: Path,
    journals_path: Path,
    suggestions_path: Path,
    index_path: Path,
    apply: bool = False,
    text_out_dir: Path | None = None,
    review_report_path: Path | None = None,
    apply_low_confidence: bool = False,
    dry_run: bool = False,
    dry_run_report_path: Path | None = None,
    verbose: bool = False,
) -> tuple[
    list[ManualSource],
    list[ParsedManualSource],
    list[dict[str, Any]],
    dict[str, Any],
]:
    validate_journal_file(journals_path)
    sources = load_manual_manifest(manifest_path)
    parsed = parse_manual_sources(sources, text_out_dir=text_out_dir)
    suggestions = generate_curation_suggestions(parsed)
    write_suggestions(suggestions, suggestions_path)
    if review_report_path is not None:
        write_review_report(
            suggestions,
            parsed,
            review_report_path,
            journals_path=journals_path,
        )
    apply_result: dict[str, Any] = {
        "applied": 0,
        "skipped_unknown": [],
        "dry_run": dry_run,
    }
    dry_run_result: dict[str, Any] = {}
    if dry_run and dry_run_report_path is not None:
        dry_run_result = build_dry_run_report(
            suggestions,
            journals_path,
            dry_run_report_path,
            include_low_confidence=apply_low_confidence,
            verbose=verbose,
        )
        apply_result.update(dry_run_result)
    if apply or dry_run:
        apply_result = apply_suggestions_to_journals(
            suggestions,
            journals_path,
            include_low_confidence=apply_low_confidence,
            dry_run=dry_run,
        )
        apply_result.update(dry_run_result)
    validate_journal_file(journals_path)
    rebuild_index(journals_path, index_path)
    return sources, parsed, suggestions, apply_result
