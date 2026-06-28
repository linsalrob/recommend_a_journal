from __future__ import annotations

from pathlib import Path

import yaml

from journal_recommender.manual_sources import (
    apply_suggestions_to_journals,
    build_dry_run_report,
    extract_relevant_sections,
    extract_text_from_file,
    generate_curation_suggestions,
    load_manual_manifest,
    parse_manual_sources,
    process_manual_sources,
    section_text_for_field,
    write_review_report,
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

    assert "article_types" not in suggestions[0]["candidate_updates"]
    assert suggestions[0]["confidence"]["scope_tags"] == "high"
    assert suggestions[0]["status"] == "ready_for_review"
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
                "confidence": {"homepage_url": "high"},
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


def test_extracts_clean_scope_section_from_noisy_html(tmp_path: Path) -> None:
    path = tmp_path / "noisy.html"
    path.write_text(
        """
        <html><body>
        <nav>Related journals Microbiome Virology Bioinformatics</nav>
        <h1>Aims and scope</h1>
        <p>This journal publishes research in microbial ecology and
        environmental microbiology.</p>
        <h2>Latest articles</h2>
        <p>Research Article: machine learning for bacteriophages. 12 Jun 2026</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    text = extract_text_from_file(path)
    sections = extract_relevant_sections(text, "homepage_or_scope")

    assert "microbial ecology" in sections["aims_scope"]
    assert "machine learning" not in sections["aims_scope"]


def test_scope_tags_do_not_come_from_related_journal_navigation(tmp_path: Path) -> None:
    html = tmp_path / "cell_like.html"
    html.write_text(
        """
        <html><body>
        <nav>Related journals Microbiome Virology Bioinformatics
        Cell Host & Microbe</nav>
        <h1>Mission and Scope</h1>
        <p>The journal publishes substantial advances of broad interest across
        life sciences.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    manifest = write_manifest(
        tmp_path,
        [{"local_file": str(html), "url": "https://example.org/cell"}],
    )

    suggestions = generate_curation_suggestions(
        parse_manual_sources(load_manual_manifest(manifest))
    )
    tags = suggestions[0]["candidate_updates"].get("scope_tags", {}).get("add", [])

    assert "microbiome" not in tags
    assert "bioinformatics" not in tags


def test_article_types_do_not_come_from_latest_article_feed(tmp_path: Path) -> None:
    html = tmp_path / "science_like.html"
    html.write_text(
        """
        <html><body>
        <h1>Aims and scope</h1>
        <p>Science publishes original research of broad scientific importance.</p>
        <h2>Latest articles</h2>
        <p>Review: microbial genomics in hospitals. 4 May 2026</p>
        <p>Research Article: new method for virome analysis. 5 May 2026</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    manifest = write_manifest(
        tmp_path,
        [{"local_file": str(html), "url": "https://example.org/science"}],
    )

    suggestion = generate_curation_suggestions(
        parse_manual_sources(load_manual_manifest(manifest))
    )[0]

    assert "article_types" not in suggestion["candidate_updates"]


def test_article_types_from_true_article_types_section(tmp_path: Path) -> None:
    html = tmp_path / "authors.html"
    html.write_text(
        """
        <html><body>
        <h1>Article types</h1>
        <p>The journal accepts Research Articles, Reviews, Brief Reports, and
        Short Communications.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    source = load_manual_manifest(
        write_manifest(
            tmp_path,
            [{"local_file": str(html), "url": "https://example.org/authors"}],
        )
    )[0]
    source.source_type = "author_instructions"

    suggestion = generate_curation_suggestions(parse_manual_sources([source]))[0]

    assert suggestion["candidate_updates"]["article_types"]["add"] == [
        "Brief Report",
        "Research Article",
        "Review",
        "Short Communication",
    ]
    assert suggestion["confidence"]["article_types"] == "high"


def test_data_and_code_policy_from_author_instructions(tmp_path: Path) -> None:
    html = tmp_path / "authors.html"
    html.write_text(
        """
        <html><body>
        <h1>Information for authors</h1>
        <p>Authors must include a data availability statement. Software and code
        used for central analyses should be made available.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    source = load_manual_manifest(
        write_manifest(
            tmp_path,
            [{"local_file": str(html), "url": "https://example.org/authors"}],
        )
    )[0]
    source.source_type = "author_instructions"
    source.target_fields = ["data_policy", "code_policy"]

    suggestion = generate_curation_suggestions(parse_manual_sources([source]))[0]

    assert suggestion["candidate_updates"]["data_policy"]["summary"]
    assert suggestion["candidate_updates"]["code_policy"]["summary"]
    assert suggestion["confidence"]["data_policy"] == "medium"


def test_full_page_fallback_is_low_confidence(tmp_path: Path) -> None:
    text = (
        "This journal publishes research in microbiology and microbial genomics "
        "and includes aims and scope information without a clean heading."
    )
    sections = extract_relevant_sections(text, "aims_scope")

    assert section_text_for_field(sections, "scope_tags", "aims_scope")
    source = load_manual_manifest(
        write_manifest(
            tmp_path,
            [{"local_file": str(tmp_path / "source.txt"), "url": "https://example.org/scope"}],
        )
    )[0]
    source.source_type = "aims_scope"
    source.target_fields = ["scope_tags"]
    source.local_file.write_text(text, encoding="utf-8")
    suggestion = generate_curation_suggestions(parse_manual_sources([source]))[0]
    assert suggestion["confidence"]["scope_tags"] == "low"
    assert suggestion["status"] == "low_confidence"


def test_review_report_is_generated(tmp_path: Path) -> None:
    suggestions = [
        {
            "journal": "Example Journal",
            "source_type": "aims_scope",
            "local_file": "manual.html",
            "status": "ready_for_review",
            "confidence": {"scope_tags": "high"},
            "warnings": [],
        }
    ]
    report = tmp_path / "manual_curation_review.md"

    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)

    write_review_report(suggestions, [], report, journals_path=journals)

    text = report.read_text(encoding="utf-8")
    assert "# Manual Curation Review" in text
    assert "## URL-only Suggestions" in text
    assert "## Missing Field Summary" in text
    assert "safe_to_apply:" in text
    assert "scope_tags" in text


def test_gitignore_contains_manual_raw_paths() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "data_manual/pages/" in gitignore
    assert "data_manual/extracted/" in gitignore


def test_url_only_suggestions_are_grouped_in_review_report(tmp_path: Path) -> None:
    suggestions = [
        {
            "journal": "Example Journal",
            "source_type": "homepage_or_scope",
            "local_file": "manual.html",
            "status": "ready_for_review",
            "candidate_updates": {"homepage_url": "https://example.org"},
            "confidence": {"homepage_url": "high"},
            "warnings": [],
        }
    ]
    report = tmp_path / "review.md"

    write_review_report(suggestions, [], report)

    text = report.read_text(encoding="utf-8")
    assert "## URL-only Suggestions" in text
    assert "Example Journal" in text


def test_dry_run_report_creation_and_no_journal_edit(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    before = journals.read_text(encoding="utf-8")
    suggestions = [
        {
            "journal": "Example Journal",
            "source_type": "aims_scope",
            "source_url": "https://example.org/scope",
            "local_file": "manual.html",
            "candidate_updates": {
                "scope_tags": {"add": ["microbiology"]},
                "manuscript_tags": {"add": ["specialist_audience"]},
            },
            "confidence": {"scope_tags": "high", "manuscript_tags": "low"},
        }
    ]
    report = tmp_path / "manual_apply_dry_run.md"

    result = build_dry_run_report(suggestions, journals, report)

    assert result["would_apply"] == 1
    assert result["skipped_low_confidence"] == 1
    assert "# Manual Apply Dry Run" in report.read_text(encoding="utf-8")
    assert "Fields that would actually change: 1" in report.read_text(
        encoding="utf-8"
    )
    assert journals.read_text(encoding="utf-8") == before


def test_dry_run_suppresses_identical_preserves_by_default(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    suggestions = [
        {
            "journal": "Example Journal",
            "source_type": "homepage_or_scope",
            "source_url": "https://example.org",
            "local_file": "manual.html",
            "candidate_updates": {
                "article_types": {"add": ["Research Article"]},
                "homepage_url": "https://example.org",
            },
            "confidence": {"article_types": "high", "homepage_url": "high"},
        }
    ]
    report = tmp_path / "dry_run.md"

    build_dry_run_report(suggestions, journals, report)

    text = report.read_text(encoding="utf-8")
    assert "Fields already identical: 1" in text
    assert "Research Article" not in text
    assert "homepage_url" in text


def test_process_manual_sources_dry_run_does_not_edit_journals(tmp_path: Path) -> None:
    html = tmp_path / "manual.html"
    html.write_text(
        """
        <html><body><h1>Aims and scope</h1>
        <p>This journal publishes microbiology research.</p></body></html>
        """,
        encoding="utf-8",
    )
    manifest = write_manifest(
        tmp_path,
        [{"local_file": str(html), "url": "https://example.org/journal"}],
    )
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    before = journals.read_text(encoding="utf-8")

    process_manual_sources(
        manifest_path=manifest,
        journals_path=journals,
        suggestions_path=tmp_path / "suggestions.yaml",
        index_path=tmp_path / "index.jsonl",
        dry_run=True,
        review_report_path=tmp_path / "review.md",
        dry_run_report_path=tmp_path / "dry_run.md",
    )

    assert (tmp_path / "dry_run.md").exists()
    assert journals.read_text(encoding="utf-8") == before


def test_apply_only_high_confidence_by_default(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    suggestions = [
        {
            "journal": "Example Journal",
            "source_type": "aims_scope",
            "source_url": "https://example.org/scope",
            "local_file": "manual.html",
            "candidate_updates": {
                "scope_tags": {"add": ["microbiology"]},
                "manuscript_tags": {"add": ["specialist_audience"]},
            },
            "confidence": {"scope_tags": "high", "manuscript_tags": "low"},
        }
    ]

    apply_suggestions_to_journals(suggestions, journals)
    records = yaml.safe_load(journals.read_text(encoding="utf-8"))

    assert records[0]["scope_tags"] == ["microbiology"]
    assert records[0]["manuscript_tags"] == []


def test_apply_low_confidence_requires_flag(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    suggestions = [
        {
            "journal": "Example Journal",
            "source_type": "aims_scope",
            "source_url": "https://example.org/scope",
            "local_file": "manual.html",
            "candidate_updates": {
                "scope_tags": {"add": ["microbiology"]},
                "manuscript_tags": {"add": ["specialist_audience"]},
            },
            "confidence": {"scope_tags": "high", "manuscript_tags": "low"},
        }
    ]

    apply_suggestions_to_journals(
        suggestions,
        journals,
        include_low_confidence=True,
    )
    records = yaml.safe_load(journals.read_text(encoding="utf-8"))

    assert records[0]["manuscript_tags"] == ["specialist_audience"]


def test_homepage_does_not_infer_article_types_from_author_section(
    tmp_path: Path,
) -> None:
    html = tmp_path / "homepage.html"
    html.write_text(
        """
        <html><body>
        <h1>Information for authors</h1>
        <p>The journal accepts Research Articles and Reviews.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    manifest = write_manifest(
        tmp_path,
        [{"local_file": str(html), "url": "https://example.org/home"}],
    )

    suggestion = generate_curation_suggestions(
        parse_manual_sources(load_manual_manifest(manifest))
    )[0]

    assert "article_types" not in suggestion["candidate_updates"]


def test_noisy_reviewer_text_rejects_article_types(tmp_path: Path) -> None:
    html = tmp_path / "authors.html"
    html.write_text(
        """
        <html><body>
        <h1>Article types</h1>
        <p>Reviewers FAQ contact us submit manuscript latest current issue
        Review Research Article 12 Jun 2026.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    source = load_manual_manifest(
        write_manifest(
            tmp_path,
            [{"local_file": str(html), "url": "https://example.org/authors"}],
        )
    )[0]
    source.source_type = "author_instructions"

    suggestion = generate_curation_suggestions(parse_manual_sources([source]))[0]

    assert "article_types" not in suggestion["candidate_updates"]
    assert suggestion["status"] == "rejected_noise"


def test_empty_policy_summary_is_not_high_confidence(tmp_path: Path) -> None:
    html = tmp_path / "authors.html"
    html.write_text(
        """
        <html><body>
        <h1>Data policy</h1>
        <p>Authors should follow the instructions for authors carefully.</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    source = load_manual_manifest(
        write_manifest(
            tmp_path,
            [{"local_file": str(html), "url": "https://example.org/authors"}],
        )
    )[0]
    source.source_type = "author_instructions"
    source.target_fields = ["data_policy"]

    suggestion = generate_curation_suggestions(parse_manual_sources([source]))[0]

    assert "data_policy" not in suggestion["candidate_updates"]
    assert suggestion["status"] in {"missing_relevant_section", "rejected_noise"}
