from __future__ import annotations

from journal_recommender.cli import main


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
