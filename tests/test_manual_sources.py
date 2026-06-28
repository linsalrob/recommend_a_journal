from __future__ import annotations

from pathlib import Path

import yaml

from journal_recommender.manual_sources import (
    apply_suggestions_to_journals,
    extract_text_from_file,
    generate_curation_suggestions,
    load_manual_manifest,
    parse_manual_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_minimal_journals(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "journal": "Example Journal",
                    "abbreviated_title": "Ex J",
                    "publisher": "Example Publisher",
                    "issn": {"print": "", "online": ""},
                    "homepage_url": "",
                    "aims_scope_url": "",
                    "author_instructions_url": "",
                    "article_types": ["Research Article"],
                    "scope_tags": [],
                    "manuscript_tags": [],
                    "suitable_for": [],
                    "less_suitable_for": [],
                    "data_policy": {"summary": "", "url": ""},
                    "code_policy": {"summary": "", "url": ""},
                    "open_access": {
                        "model": "",
                        "apc": None,
                        "currency": "",
                        "url": "",
                    },
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
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_manifest_loading_and_html_parsing(tmp_path: Path) -> None:
    html = tmp_path / "manual.html"
    html.write_text((REPO_ROOT / "tests/fixtures/manual_source.html").read_text())
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "manual_sources": [
                    {
                        "journal": "Example Journal",
                        "source_type": "homepage_or_scope",
                        "url": "https://example.org/journal",
                        "local_file": str(html),
                        "target_fields": ["article_types", "scope_tags"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    sources = load_manual_manifest(manifest)
    parsed = parse_manual_sources(sources, text_out_dir=tmp_path / "extracted")

    assert len(sources) == 1
    assert parsed[0].status == "parsed"
    assert "script" not in parsed[0].text.lower()
    assert Path(parsed[0].extracted_text_path).exists()


def test_missing_and_failed_local_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.html"
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF")
    sources = [
        load_manual_manifest(
            write_manifest(
                tmp_path,
                [
                    {"local_file": str(missing), "url": "https://example.org/a"},
                    {"local_file": str(pdf), "url": "https://example.org/b"},
                ],
            )
        )[0],
        load_manual_manifest(
            write_manifest(
                tmp_path / "second",
                [{"local_file": str(pdf), "url": "https://example.org/b"}],
            )
        )[0],
    ]

    parsed = parse_manual_sources(sources)

    assert parsed[0].status == "missing_local_file"
    assert parsed[1].status == "parsing_failed"


def write_manifest(base: Path, entries: list[dict]) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    path = base / "manifest.yaml"
    sources = []
    for entry in entries:
        sources.append(
            {
                "journal": "Example Journal",
                "source_type": "homepage_or_scope",
                "url": entry["url"],
                "local_file": entry["local_file"],
                "target_fields": ["article_types", "scope_tags"],
            }
        )
    path.write_text(yaml.safe_dump({"manual_sources": sources}), encoding="utf-8")
    return path


def test_suggestion_generation_and_apply(tmp_path: Path) -> None:
    html = tmp_path / "manual.html"
    html.write_text((REPO_ROOT / "tests/fixtures/manual_source.html").read_text())
    manifest = write_manifest(
        tmp_path,
        [{"local_file": str(html), "url": "https://example.org/journal"}],
    )
    sources = load_manual_manifest(manifest)
    parsed = parse_manual_sources(sources)
    suggestions = generate_curation_suggestions(parsed)
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)

    result = apply_suggestions_to_journals(suggestions, journals)
    records = yaml.safe_load(journals.read_text(encoding="utf-8"))

    assert suggestions[0]["candidate_updates"]["article_types"]["add"]
    assert result["applied"] > 0
    assert records[0]["article_types"].count("Research Article") == 1
    assert records[0]["scope_tags"]
    assert records[0]["source_evidence"]


def test_apply_does_not_overwrite_curated_scalar(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    records = yaml.safe_load(journals.read_text(encoding="utf-8"))
    records[0]["homepage_url"] = "https://curated.example.org"
    journals.write_text(yaml.safe_dump(records, sort_keys=False), encoding="utf-8")

    apply_suggestions_to_journals(
        [
            {
                "journal": "Example Journal",
                "source_type": "homepage_or_scope",
                "source_url": "https://new.example.org",
                "local_file": "manual.html",
                "candidate_updates": {"homepage_url": "https://new.example.org"},
            }
        ],
        journals,
    )

    records = yaml.safe_load(journals.read_text(encoding="utf-8"))
    assert records[0]["homepage_url"] == "https://curated.example.org"


def test_extract_text_from_txt(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("Aims   and   scope", encoding="utf-8")

    assert extract_text_from_file(path) == "Aims and scope"
