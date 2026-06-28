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
    text_parts = [
        journal.journal,
        journal.abbreviated_title,
        journal.publisher,
        " ".join(journal.scope_tags),
        " ".join(journal.manuscript_tags),
        " ".join(journal.suitable_for),
        " ".join(journal.less_suitable_for),
        journal.data_policy.summary,
        journal.code_policy.summary,
        " ".join(journal.editorial_notes),
        " ".join(source_urls),
    ]
    text = "\n".join(part for part in text_parts if part)

    return {
        "journal": journal.journal,
        "document_type": "journal_profile",
        "text": text,
        "metadata": {
            "publisher": journal.publisher,
            "source_urls": source_urls,
            "last_checked": journal.last_checked,
        },
    }


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
