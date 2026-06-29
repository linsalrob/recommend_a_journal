from __future__ import annotations

from pathlib import Path

from journal_recommender.cli import main
from tests.test_manual_sources import write_manifest, write_minimal_journals

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_validate_journals_cli(capsys) -> None:
    exit_code = main(["validate-journals", "data/journals.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validated 35 journal records" in captured.out


def test_validate_manuscript_cli(capsys) -> None:
    exit_code = main(
        ["validate-manuscript", "data/examples/microbiome_cohort_features.yaml"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validated manuscript feature file" in captured.out


def test_rank_journals_cli(tmp_path, capsys) -> None:
    out = tmp_path / "recommendation.md"
    exit_code = main(
        [
            "rank-journals",
            "--manuscript",
            "data/examples/microbiome_cohort_features.yaml",
            "--journals",
            "data/journals.yaml",
            "--out",
            str(out),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "top recommendation" in captured.out
    assert out.exists()


def test_audit_metrics_cli(tmp_path, capsys) -> None:
    out = tmp_path / "metrics_audit.md"
    exit_code = main(
        [
            "audit-metrics",
            "--journals",
            "data/journals.yaml",
            "--out",
            str(out),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Audited 35 journals" in captured.out
    assert out.exists()


def test_process_manual_sources_cli(tmp_path, capsys) -> None:
    html = tmp_path / "manual.html"
    html.write_text(
        "<html><body><h1>Aims and scope</h1>"
        "<p>Research Article microbiology software methods.</p></body></html>",
        encoding="utf-8",
    )
    manifest = write_manifest(
        tmp_path,
        [{"local_file": str(html), "url": "https://example.org/journal"}],
    )
    journals = tmp_path / "journals.yaml"
    write_minimal_journals(journals)
    exit_code = main(
        [
            "process-manual-sources",
            "--manifest",
            str(manifest),
            "--journals",
            str(journals),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--suggestions",
            str(tmp_path / "suggestions.yaml"),
            "--manual-download-report",
            str(tmp_path / "queue.md"),
            "--manual-download-yaml",
            str(tmp_path / "queue.yaml"),
            "--index",
            str(tmp_path / "index.jsonl"),
            "--review-report",
            str(tmp_path / "review.md"),
            "--dry-run-report",
            str(tmp_path / "dry_run.md"),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Processed manual sources" in captured.out
    assert "(dry run)" in captured.out
    assert (tmp_path / "suggestions.yaml").exists()
    assert (tmp_path / "review.md").exists()
    assert (tmp_path / "dry_run.md").exists()


def test_extract_features_cli(tmp_path, capsys) -> None:
    manuscript = tmp_path / "microbiome_cohort.txt"
    manuscript.write_text(
        (REPO_ROOT / "tests/fixtures/manuscripts/microbiome_cohort.txt").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    out = tmp_path / "draft.yaml"
    text_out = tmp_path / "extracted.txt"

    exit_code = main(
        [
            "extract-features",
            "--manuscript",
            str(manuscript),
            "--out",
            str(out),
            "--text-out",
            str(text_out),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert out.exists()
    assert text_out.exists()
    assert "Extracted manuscript features" in captured.out
