from __future__ import annotations

from journal_recommender.cli import main


def test_validate_journals_cli(capsys) -> None:
    exit_code = main(["validate-journals", "data/journals.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validated 35 journal records" in captured.out
