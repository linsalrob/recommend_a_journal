from __future__ import annotations

from journal_recommender.cli import main
from tests.test_manual_sources import write_manifest, write_minimal_journals


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
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Processed manual sources" in captured.out
    assert (tmp_path / "suggestions.yaml").exists()
