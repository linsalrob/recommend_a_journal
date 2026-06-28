from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import yaml

from journal_recommender.cli import main
from journal_recommender.schema import JournalRecord
from journal_recommender.updating import (
    ApcResult,
    CrossrefResult,
    PoliteFetcher,
    UpdateReport,
    UrlCache,
    apply_crossref_updates,
    classify_url_result,
    crossref_matches_journal,
    fetch_crossref_metadata,
    generate_report_from_latest,
    parse_apc_amount,
    render_change_report,
    run_journal_update,
    stable_content_hash,
    write_report_json,
)


class FakeHeaders(dict):
    def get(self, key: str, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def getcode(self) -> int:
        return self.status_code

    def read(self) -> bytes:
        return self.body


def complete_record(journal: str, url: str = "https://example.org") -> dict:
    return {
        "journal": journal,
        "abbreviated_title": "",
        "publisher": "",
        "issn": {"print": "", "online": ""},
        "homepage_url": url,
        "aims_scope_url": "",
        "author_instructions_url": "",
        "article_types": [],
        "scope_tags": [],
        "manuscript_tags": [],
        "suitable_for": [],
        "less_suitable_for": [],
        "data_policy": {"summary": "", "url": ""},
        "code_policy": {"summary": "", "url": ""},
        "open_access": {"model": "", "apc": None, "currency": "", "url": ""},
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


def test_url_cache_load_save(tmp_path: Path) -> None:
    cache = UrlCache(tmp_path / "cache")
    cache.load()
    cache.set(
        "https://example.org",
        {
            "url": "https://example.org",
            "last_checked": "2026-06-28",
            "status_code": 200,
            "etag": "abc",
            "last_modified": "",
            "content_hash": "hash",
            "content_path": "page.html",
            "error": "",
        },
    )
    cache.save()

    reloaded = UrlCache(tmp_path / "cache")
    reloaded.load()

    assert reloaded.get("https://example.org")["etag"] == "abc"
    assert reloaded.hashes["https://example.org"] == "hash"


def test_stable_content_hash_normalises_whitespace() -> None:
    assert stable_content_hash("alpha   beta") == stable_content_hash("alpha beta")


def test_url_detection_unchanged_changed_and_new() -> None:
    unchanged = classify_url_result(
        "Journal",
        "https://example.org",
        {"content_hash": "abc"},
        {"content_hash": "abc", "status_code": 200, "error": ""},
        "2026-06-28",
    )
    changed = classify_url_result(
        "Journal",
        "https://example.org",
        {"content_hash": "abc"},
        {"content_hash": "def", "status_code": 200, "error": ""},
        "2026-06-28",
    )
    new = classify_url_result(
        "Journal",
        "https://example.org",
        {},
        {"content_hash": "def", "status_code": 200, "error": ""},
        "2026-06-28",
    )

    assert unchanged.status == "unchanged"
    assert changed.status == "changed"
    assert new.status == "new"


def test_non_fatal_http_failure_is_recorded(tmp_path: Path) -> None:
    def opener(*args, **kwargs):
        raise HTTPError(
            url="https://example.org",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=None,
        )

    cache = UrlCache(tmp_path / "cache")
    cache.load()
    fetcher = PoliteFetcher(cache, delay_seconds=0, opener=opener)

    entry = fetcher.fetch("https://example.org", "2026-06-28")

    assert entry["status_code"] == 503
    assert entry["error"] == "HTTP 503"


def test_crossref_matching_logic_uses_issn_or_title() -> None:
    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "issn": {"print": "1234-5678", "online": ""},
        }
    )

    assert crossref_matches_journal(journal, {"ISSN": ["1234-5678"]})
    assert crossref_matches_journal(journal, {"title": "Example Journal"})
    assert not crossref_matches_journal(journal, {"title": "Other Journal"})


def test_crossref_fetch_with_mocked_response() -> None:
    def opener(request, timeout):
        payload = {
            "message": {
                "ISSN": ["1234-5678"],
                "title": "Example Journal",
                "publisher": "Example Publisher",
            }
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "issn": {"print": "1234-5678", "online": ""},
        }
    )

    result = fetch_crossref_metadata(journal, opener=opener)

    assert result.status == "matched"
    assert result.updates["publisher"] == "Example Publisher"


def test_crossref_updates_apply_only_missing_fields(tmp_path: Path) -> None:
    journals_path = tmp_path / "journals.yaml"
    record = complete_record("Example Journal")
    record["issn"] = {"print": "1234-5678", "online": ""}
    journals_path.write_text(yaml.safe_dump([record]), encoding="utf-8")

    updated = apply_crossref_updates(
        journals_path,
        [
            CrossrefResult(
                journal="Example Journal",
                status="matched",
                updates={"publisher": "Example Publisher"},
            )
        ],
    )

    records = yaml.safe_load(journals_path.read_text(encoding="utf-8"))
    assert updated == 1
    assert records[0]["publisher"] == "Example Publisher"


def test_apc_parsing_is_conservative() -> None:
    assert parse_apc_amount("Article processing charge: USD 1,250") == (1250, "USD")
    assert parse_apc_amount("APC: USD 1000 or EUR 900") is None
    assert parse_apc_amount("No amount here") is None


def test_report_generation_contains_summary() -> None:
    report = UpdateReport(
        run_date="2026-06-28",
        trigger="local",
        journals_checked=1,
        crossref_results=[
            CrossrefResult(
                journal="Example Journal",
                status="matched",
                updates={"publisher": "Example Publisher"},
            )
        ],
        apc_results=[
            ApcResult(
                journal="Example Journal",
                status="needs_review",
                source_url="https://example.org/apc",
                note="Manual review required.",
            )
        ],
    )

    markdown = render_change_report(report)

    assert "Journals checked: 1" in markdown
    assert "Crossref records updated: 1" in markdown
    assert "APCs needing review: 1" in markdown


def test_run_journal_update_with_mocked_http(tmp_path: Path) -> None:
    journals_path = tmp_path / "journals.yaml"
    journals_path.write_text(
        yaml.safe_dump([complete_record("Example Journal")]),
        encoding="utf-8",
    )

    def opener(request, timeout):
        url = request.full_url
        if "api.crossref.org" in url:
            return FakeResponse(json.dumps({"message": {}}).encode("utf-8"))
        return FakeResponse(b"<html>Example page</html>")

    report = run_journal_update(
        journals_path=journals_path,
        cache_dir=tmp_path / "cache",
        report_path=tmp_path / "report.md",
        delay_seconds=0,
        opener=opener,
        sleeper=lambda seconds: None,
    )

    assert report.journals_checked == 1
    assert report.url_results[0].status == "new"
    assert (tmp_path / "cache" / "url_cache.json").exists()
    assert (tmp_path / "report.md").exists()


def test_generate_report_from_latest_records_index_status(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    index_path = tmp_path / "index.jsonl"
    index_path.write_text("{}", encoding="utf-8")
    write_report_json(
        UpdateReport(run_date="2026-06-28", trigger="local", journals_checked=1),
        cache_dir / "latest_update_report.json",
    )

    report = generate_report_from_latest(
        cache_dir,
        tmp_path / "report.md",
        index_path,
    )

    assert "Rebuilt index" in report.index_status
    assert "Rebuilt index" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_cli_update_rebuild_and_report_commands(monkeypatch, tmp_path: Path) -> None:
    def fake_update(**kwargs):
        return UpdateReport(run_date="2026-06-28", trigger="local", journals_checked=1)

    def fake_rebuild(journals_path, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}", encoding="utf-8")
        return 1

    def fake_report(cache_dir, report_path, index_path):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# Report", encoding="utf-8")
        return UpdateReport(run_date="2026-06-28", trigger="local", journals_checked=1)

    monkeypatch.setattr("journal_recommender.cli.run_journal_update", fake_update)
    monkeypatch.setattr("journal_recommender.cli.rebuild_index", fake_rebuild)
    monkeypatch.setattr(
        "journal_recommender.cli.generate_report_from_latest",
        fake_report,
    )

    assert main(["update-journals", "--report", str(tmp_path / "report.md")]) == 0
    assert main(["rebuild-index", "--out", str(tmp_path / "index.jsonl")]) == 0
    assert main(["report-changes", "--report", str(tmp_path / "report.md")]) == 0
