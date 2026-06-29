"""Build lightweight retrieval corpora from curated journal records."""

from __future__ import annotations

import json
from pathlib import Path

from journal_recommender.schema import JournalRecord, validate_journal_file

DEFAULT_INDEX_PATH = Path("data/index/journal_corpus.jsonl")


def rebuild_index(
    journals_path: Path,
    output_path: Path = DEFAULT_INDEX_PATH,
) -> int:
    journals = validate_journal_file(journals_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for journal in journals:
            handle.write(json.dumps(index_record(journal), sort_keys=True))
            handle.write("\n")

    return len(journals)


def index_record(journal: JournalRecord) -> dict:
    source_urls = collect_source_urls(journal)
    prestige_metrics = journal.prestige_metrics.model_dump()
    curated_apc = (
        f"{journal.open_access.apc} {journal.open_access.currency}".strip()
        if journal.open_access.apc is not None
        else ""
    )
    text_parts = [
        f"Journal: {journal.journal}",
        f"Abbreviated title: {journal.abbreviated_title}",
        f"Publisher: {journal.publisher}",
        f"Print ISSN: {journal.issn.print}",
        f"Online ISSN: {journal.issn.online}",
        f"Article types: {', '.join(journal.article_types)}",
        f"Scope tags: {', '.join(journal.scope_tags)}",
        f"Manuscript tags: {', '.join(journal.manuscript_tags)}",
        f"Suitable for: {', '.join(journal.suitable_for)}",
        f"Less suitable for: {', '.join(journal.less_suitable_for)}",
        f"Data policy: {journal.data_policy.summary}",
        f"Code policy: {journal.code_policy.summary}",
        f"Open access model: {journal.open_access.model}",
        f"Curated APC: {curated_apc}",
        f"Prestige metrics: {format_prestige_metrics(prestige_metrics)}",
        f"Editorial notes: {' '.join(journal.editorial_notes)}",
        f"Source URLs: {' '.join(source_urls)}",
    ]
    text = "\n".join(part for part in text_parts if not part.endswith(": "))

    return {
        "journal": journal.journal,
        "abbreviated_title": journal.abbreviated_title,
        "publisher": journal.publisher,
        "issn": journal.issn.model_dump(),
        "article_types": journal.article_types,
        "scope_tags": journal.scope_tags,
        "manuscript_tags": journal.manuscript_tags,
        "suitable_for": journal.suitable_for,
        "less_suitable_for": journal.less_suitable_for,
        "data_policy": journal.data_policy.model_dump(),
        "code_policy": journal.code_policy.model_dump(),
        "open_access": journal.open_access.model_dump(),
        "prestige_metrics": prestige_metrics,
        "editorial_notes": journal.editorial_notes,
        "source_urls": source_urls,
        "last_checked": journal.last_checked,
        "document_type": "journal_profile",
        "text": text,
        "metadata": {
            "publisher": journal.publisher,
            "issn": journal.issn.model_dump(),
            "source_urls": source_urls,
            "last_checked": journal.last_checked,
        },
    }


def format_prestige_metrics(metrics: dict) -> str:
    return ", ".join(
        f"{key}={value}"
        for key, value in metrics.items()
        if not is_empty_metric_value(value)
    )


def is_empty_metric_value(value: object) -> bool:
    if isinstance(value, dict):
        return all(is_empty_metric_value(item) for item in value.values())
    if isinstance(value, list):
        return not value
    if value in {None, ""}:
        return True
    return False


def collect_source_urls(journal: JournalRecord) -> list[str]:
    urls = [
        journal.homepage_url,
        journal.aims_scope_url,
        journal.author_instructions_url,
        journal.data_policy.url,
        journal.code_policy.url,
        journal.open_access.url,
    ]
    urls.extend(example.url for example in journal.example_papers)
    urls.extend(evidence.url for evidence in journal.source_evidence)
    seen: set[str] = set()
    clean_urls: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        clean_urls.append(url)
    return clean_urls
