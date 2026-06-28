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
    "Research Article": r"\b(research article|original research|article)\b",
    "Review": r"\b(review article|review)\b",
    "Brief Report": r"\b(brief report|brief communication)\b",
    "Short Communication": r"\b(short communication|short report)\b",
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
    text = parsed.text
    candidates: dict[str, Any] = {}
    evidence: list[dict[str, str]] = []
    warnings: list[str] = []

    if "homepage_url" in source.target_fields:
        candidates["homepage_url"] = source.url
    if "aims_scope_url" in source.target_fields or source.source_type == "aims_scope":
        candidates["aims_scope_url"] = source.url
    if (
        "author_instructions_url" in source.target_fields
        or source.source_type in {"author_instructions", "guide_for_authors"}
    ):
        candidates["author_instructions_url"] = source.url

    article_types = detect_article_types(text)
    if article_types and "article_types" in source.target_fields:
        candidates["article_types"] = {"add": article_types}
        evidence.append(
            {
                "field": "article_types",
                "snippet": snippet_for_terms(text, article_types),
            }
        )

    scope_tags = detect_tags(text, SCOPE_KEYWORDS)
    if scope_tags and "scope_tags" in source.target_fields:
        candidates["scope_tags"] = {"add": scope_tags}
        snippet = snippet_for_terms(text, scope_tags)
        if snippet:
            evidence.append({"field": "scope_tags", "snippet": snippet})

    manuscript_tags = detect_tags(text, MANUSCRIPT_KEYWORDS)
    if manuscript_tags and "manuscript_tags" in source.target_fields:
        candidates["manuscript_tags"] = {"add": manuscript_tags}

    if "data_policy" in source.target_fields:
        summary = policy_summary(text, ["data availability", "data sharing", "data"])
        candidates["data_policy"] = {"summary": summary, "url": source.url}
        if summary:
            evidence.append({"field": "data_policy", "snippet": summary})
    if "code_policy" in source.target_fields:
        summary = policy_summary(text, ["code availability", "software", "code"])
        candidates["code_policy"] = {"summary": summary, "url": source.url}
        if summary:
            evidence.append({"field": "code_policy", "snippet": summary})
    if "open_access" in source.target_fields or source.source_type in {
        "apc",
        "open_access",
    }:
        candidates["open_access"] = open_access_candidate(source, text)
        if candidates["open_access"].get("apc") is None:
            warnings.append("APC amount not extracted confidently.")

    if "editorial_notes" in source.target_fields:
        note = editorial_note_candidate(source, text)
        if note:
            candidates["editorial_notes"] = {"add": [note]}

    return {
        "journal": source.journal,
        "source_type": source.source_type,
        "source_url": source.url,
        "local_file": str(source.local_file),
        "extracted_text_path": parsed.extracted_text_path,
        "candidate_updates": candidates,
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


def editorial_note_candidate(source: ManualSource, text: str) -> str:
    if source.source_type in {"homepage_or_scope", "aims_scope"}:
        snippet = snippet_for_terms(text, ["aims", "scope", "publishes"])
        if snippet:
            return f"Manual source suggests scope note: {snippet}"
    return ""


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
    encoded_markers = snippet.count("=20") + snippet.count("=E2") + snippet.count("=0")
    if encoded_markers:
        return False
    alnum = sum(char.isalnum() for char in snippet)
    return (alnum / max(len(snippet), 1)) > 0.45


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


def apply_suggestions_to_journals(
    suggestions: list[dict[str, Any]],
    journals_path: Path,
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
        updates = suggestion.get("candidate_updates", {})
        applied += apply_candidate_updates(record, updates)
        add_source_evidence(record, suggestion)

    with journals_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(records, handle, sort_keys=False, allow_unicode=True)

    validate_journal_file(journals_path)
    return {"applied": applied, "skipped_unknown": sorted(set(skipped_unknown))}


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
    apply_result: dict[str, Any] = {"applied": 0, "skipped_unknown": []}
    if apply:
        apply_result = apply_suggestions_to_journals(suggestions, journals_path)
    validate_journal_file(journals_path)
    rebuild_index(journals_path, index_path)
    return sources, parsed, suggestions, apply_result
