from __future__ import annotations

import json
from pathlib import Path

import yaml

import journal_recommender.manifest_journals as manifest_journals
from journal_recommender.cli import main
from journal_recommender.manifest_journals import (
    add_journals_from_manifest,
    build_manifest_journal_report,
    infer_url_field,
)
from journal_recommender.schema import JournalRecord, validate_journal_file
from tests.test_manual_sources import write_minimal_journals


def write_manifest_for_journals(
    base: Path,
    entries: list[dict[str, str]],
) -> Path:
    sources = []
    for entry in entries:
        sources.append(
            {
                "journal": entry["journal"],
                "source_type": entry["source_type"],
                "url": entry["url"],
                "local_file": entry["local_file"],
                "target_fields": entry.get("target_fields", []),
            }
        )
    path = base / "manifest.yaml"
    path.write_text(yaml.safe_dump({"manual_sources": sources}), encoding="utf-8")
    return path


def test_missing_journal_detection_and_existing_not_duplicated(
    tmp_path: Path,
) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "Example Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/example",
                "local_file": "example.html",
            },
            {
                "journal": "New Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/new",
                "local_file": "new.html",
            },
        ],
    )

    report = build_manifest_journal_report(manifest, journals)

    assert report.manifest_journal_names == 2
    assert report.already_present_journals == ["Example Journal"]
    assert report.missing_journals == 1
    assert report.added_journals == ["New Journal"]


def test_multiple_manifest_entries_merge_into_one_stub(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text("<html><body>stub</body></html>", encoding="utf-8")
    journals = tmp_path / "journals.yaml"
    journals.write_text("[]", encoding="utf-8")
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "Merged Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/home",
                "local_file": str(html),
            },
            {
                "journal": "Merged Journal",
                "source_type": "guide_for_authors",
                "url": "https://example.org/authors",
                "local_file": str(html),
            },
        ],
    )

    report = build_manifest_journal_report(manifest, journals)
    stub = report.stubs[0]

    assert report.missing_journals == 1
    assert stub.inferred_urls["homepage_url"] == "https://example.org/home"
    assert stub.inferred_urls["author_instructions_url"] == "https://example.org/authors"
    assert len(stub.record["source_evidence"]) == 2
    assert stub.source_types == ["guide_for_authors", "homepage_or_scope"]


def test_url_field_inference_by_source_type() -> None:
    assert infer_url_field("homepage_or_scope") == "homepage_url"
    assert infer_url_field("aims_scope") == "aims_scope_url"
    assert infer_url_field("guide_for_authors") == "author_instructions_url"
    assert infer_url_field("data_policy") == "data_policy.url"
    assert infer_url_field("code_policy") == "code_policy.url"
    assert infer_url_field("apc") == "open_access.url"


def test_generated_stubs_validate_with_existing_schema(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text("<html><body>stub</body></html>", encoding="utf-8")
    journals = tmp_path / "journals.yaml"
    journals.write_text("[]", encoding="utf-8")
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "Valid Stub Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/home",
                "local_file": str(html),
            }
        ],
    )

    report = build_manifest_journal_report(manifest, journals)
    JournalRecord.model_validate(report.stubs[0].record)


def test_dry_run_does_not_modify_journals_yaml(tmp_path: Path) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    original = journals.read_text(encoding="utf-8")
    html = tmp_path / "page.html"
    html.write_text("<html><body>stub</body></html>", encoding="utf-8")
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "Dry Run Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/home",
                "local_file": str(html),
            }
        ],
    )
    out = tmp_path / "report.md"

    report = add_journals_from_manifest(
        manifest,
        journals,
        out,
        dry_run=True,
    )

    assert journals.read_text(encoding="utf-8") == original
    assert report.mode == "dry-run"
    assert out.exists()


def test_apply_mode_appends_valid_records_and_enriches_metrics(
    tmp_path: Path,
) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    html = tmp_path / "page.html"
    html.write_text("<html><body>stub</body></html>", encoding="utf-8")
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "Applied Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/home",
                "local_file": str(html),
            },
            {
                "journal": "Applied Journal",
                "source_type": "guide_for_authors",
                "url": "https://example.org/authors",
                "local_file": str(html),
            },
        ],
    )
    scimago = tmp_path / "scimagojr_2025.csv"
    scimago.write_text(
        (
            "Rank;Sourceid;Title;Type;Issn;Publisher;Open Access;Open Access "
            "Diamond;SJR;SJR Best Quartile;H index;Total Docs. (2025);Total Docs. "
            "(3years);Total Refs.;Total Citations (3years);Citable Docs. (3years);"
            "Citations / Doc. (2years);Ref. / Doc.;%Female;Overton;Country;Region;"
            "Publisher;Coverage;Categories;Areas\n"
            '1;1;"Applied Journal";journal;"";"Example Publisher";No;No;1.234;Q2;'
            '17;1;1;1;1;1;1;1;1;1;1;"Example Publisher";"2020-2025";'
            '"Microbiology (Q2)";"Medicine"\n'
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report.md"
    index_path = tmp_path / "index.jsonl"

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def opener(request, timeout):
        payload = {
            "results": [
                {
                    "display_name": "Applied Journal",
                    "id": "https://openalex.org/S123",
                    "issn_l": "",
                    "issn": [],
                    "works_count": 10,
                    "cited_by_count": 20,
                    "counts_by_year": [
                        {"year": 2025, "works_count": 5, "cited_by_count": 10},
                        {"year": 2024, "works_count": 5, "cited_by_count": 10},
                    ],
                    "summary_stats": {"h_index": 5},
                }
            ]
        }
        return FakeResponse(payload)

    report = add_journals_from_manifest(
        manifest,
        journals,
        out,
        apply=True,
        rebuild_index=True,
        index_path=index_path,
        openalex_opener=opener,
        scimago_path=scimago,
    )

    records = yaml.safe_load(journals.read_text(encoding="utf-8"))
    new_record = next(
        record for record in records if record["journal"] == "Applied Journal"
    )

    assert report.mode == "apply"
    assert report.scimago_updates == 1
    assert report.openalex_updates == 1
    assert len(records) == 2
    assert new_record["prestige_metrics"]["sjr"] == 1.234
    assert new_record["prestige_metrics"]["openalex"]["openalex_source_id"] == "S123"
    assert validate_journal_file(journals)[-1].journal == "Applied Journal"
    assert index_path.exists()


def test_apply_mode_uses_default_openalex_opener_when_none(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    html = tmp_path / "page.html"
    html.write_text("<html><body>stub</body></html>", encoding="utf-8")
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "Default Opener Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/home",
                "local_file": str(html),
            }
        ],
    )
    out = tmp_path / "report.md"
    scimago = tmp_path / "missing_scimago.csv"
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"results": []}).encode("utf-8")

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(manifest_journals, "urlopen", opener)

    report = add_journals_from_manifest(
        manifest,
        journals,
        out,
        apply=True,
        scimago_path=scimago,
    )

    assert report.mode == "apply"
    assert report.openalex_updates == 0
    assert len(calls) == 1
    assert out.exists()


def test_cli_add_journals_from_manifest_reports_and_dry_runs(
    tmp_path: Path,
    capsys,
) -> None:
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    html = tmp_path / "page.html"
    html.write_text("<html><body>stub</body></html>", encoding="utf-8")
    manifest = write_manifest_for_journals(
        tmp_path,
        [
            {
                "journal": "CLI Journal",
                "source_type": "homepage_or_scope",
                "url": "https://example.org/home",
                "local_file": str(html),
            }
        ],
    )
    out = tmp_path / "report.md"

    exit_code = main(
        [
            "add-journals-from-manifest",
            "--manifest",
            str(manifest),
            "--journals",
            str(journals),
            "--out",
            str(out),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Processed manifest journals" in captured.out
    assert out.exists()
    assert len(yaml.safe_load(journals.read_text(encoding="utf-8"))) == 1
