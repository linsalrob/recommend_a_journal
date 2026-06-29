from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import yaml

from journal_recommender.cli import main
from journal_recommender.indexing import index_record
from journal_recommender.schema import JournalRecord
from journal_recommender.updating import (
    ApcResult,
    CrossrefResult,
    OpenAlexResult,
    PoliteFetcher,
    UpdateReport,
    UrlCache,
    apply_crossref_updates,
    apply_openalex_updates,
    apply_scimago_metrics,
    classify_content_quality,
    classify_url_result,
    crossref_matches_journal,
    fetch_crossref_metadata,
    fetch_openalex_metadata,
    generate_report_from_latest,
    mark_duplicate_hashes,
    match_scimago_row,
    openalex_matches_journal,
    openalex_metrics_from_source,
    parse_apc_amount,
    parse_scimago_float,
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
            "openalex": {
                "openalex_source_id": "",
                "works_count": None,
                "cited_by_count": None,
                "counts_by_year": [],
                "openalex_h_index": None,
                "openalex_2yr_citation_rate": None,
                "openalex_4yr_citation_rate": None,
                "metric_year": None,
                "source_url": "",
                "last_checked": "",
            },
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


def test_content_quality_flags_very_short_blocked_and_valid() -> None:
    short = classify_content_quality("<html><body>Hi</body></html>")
    blocked = classify_content_quality(
        "<html><body>Access denied. Verify you are human.</body></html>"
    )
    valid = classify_content_quality(
        "<html><body><h1>Example Journal</h1>"
        "<p>This journal publishes microbiology and computational biology "
        "research articles, methods, resources, reviews, and policy-relevant "
        "work for a specialist scientific audience.</p></body></html>"
    )

    assert "very_short_body" in short["content_quality_flags"]
    assert "blocked_or_challenge_page" in blocked["content_quality_flags"]
    assert valid["content_quality_flags"] == ["looks_valid"]


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


def test_duplicate_hash_across_many_urls_is_suspicious() -> None:
    results = [
        classify_url_result(
            "Journal",
            f"https://example.org/{index}",
            {},
            {
                "content_hash": "same",
                "status_code": 200,
                "error": "",
                "content_quality_flags": ["looks_valid"],
            },
            "2026-06-28",
        )
        for index in range(3)
    ]

    mark_duplicate_hashes(results)

    assert {result.status for result in results} == {"suspicious"}
    assert all(
        "duplicate_hash_across_many_urls" in result.content_quality_flags
        for result in results
    )


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


def test_403_and_429_are_blocked(tmp_path: Path) -> None:
    for code in [403, 429]:
        cache = UrlCache(tmp_path / f"cache-{code}")
        cache.load()

        def opener(*args, status_code=code, **kwargs):
            raise HTTPError(
                url="https://example.org",
                code=status_code,
                msg="Blocked",
                hdrs={},
                fp=None,
            )

        entry = PoliteFetcher(cache, delay_seconds=0, opener=opener).fetch(
            "https://example.org",
            "2026-06-28",
        )
        result = classify_url_result(
            "Journal",
            "https://example.org",
            {},
            entry,
            "2026-06-28",
        )

        assert result.status == "blocked"


def test_repeated_block_is_recorded(tmp_path: Path) -> None:
    cache = UrlCache(tmp_path / "cache")
    cache.load()

    def opener(*args, **kwargs):
        raise HTTPError(
            url="https://example.org",
            code=403,
            msg="Blocked",
            hdrs={},
            fp=None,
        )

    fetcher = PoliteFetcher(cache, delay_seconds=0, opener=opener)
    fetcher.fetch("https://example.org", "2026-06-28")
    fetcher.fetched_this_run.clear()
    entry = fetcher.fetch("https://example.org", "2026-07-01")

    assert entry["blocked_repeatedly"] is True


def test_redirect_loop_is_failed(tmp_path: Path) -> None:
    cache = UrlCache(tmp_path / "cache")
    cache.load()

    def opener(*args, **kwargs):
        raise OSError("redirect loop: too many redirects")

    entry = PoliteFetcher(cache, delay_seconds=0, opener=opener).fetch(
        "https://example.org",
        "2026-06-28",
    )
    result = classify_url_result("Journal", "https://example.org", {}, entry, "today")

    assert result.status == "failed"
    assert "redirect loop" in result.error


def test_manual_curation_source_url_is_skipped(tmp_path: Path) -> None:
    journals_path = tmp_path / "journals.yaml"
    record = complete_record("Example Journal", url="")
    record["source_evidence"] = [
        {
            "label": "Homepage",
            "url": "https://example.org/manual",
            "accessed": "2026-06-28",
            "notes": "manually curated only",
        }
    ]
    journals_path.write_text(yaml.safe_dump([record]), encoding="utf-8")

    report = run_journal_update(
        journals_path=journals_path,
        cache_dir=tmp_path / "cache",
        report_path=tmp_path / "report.md",
        delay_seconds=0,
        opener=lambda *args, **kwargs: FakeResponse(b"should not fetch"),
        sleeper=lambda seconds: None,
    )

    assert report.url_results[0].status == "skipped_manual"


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


def test_crossref_title_fallback_with_mocked_response() -> None:
    def opener(request, timeout):
        assert "query.title=Example%20Journal" in request.full_url
        payload = {
            "message": {
                "items": [
                    {
                        "title": "Example Journal",
                        "publisher": "Example Publisher",
                    }
                ]
            }
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    journal = JournalRecord.model_validate({"journal": "Example Journal"})

    result = fetch_crossref_metadata(journal, opener=opener)

    assert result.status == "matched"
    assert result.updates["publisher"] == "Example Publisher"


def test_crossref_title_fallback_needs_review_on_weak_match() -> None:
    def opener(request, timeout):
        payload = {
            "message": {
                "items": [
                    {
                        "title": "Example Journal Reviews",
                        "publisher": "Example Publisher",
                    }
                ]
            }
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    journal = JournalRecord.model_validate({"journal": "Example Journal"})

    result = fetch_crossref_metadata(journal, opener=opener)

    assert result.status == "needs_review"


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


def test_openalex_matching_logic_uses_issn_or_exact_title() -> None:
    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "issn": {"print": "1234-5678", "online": ""},
        }
    )

    assert openalex_matches_journal(
        journal,
        {"issn": ["1234-5678"], "display_name": "Different Title"},
    )
    assert openalex_matches_journal(journal, {"display_name": "Example Journal"})
    assert not openalex_matches_journal(
        journal,
        {"display_name": "Example Journal Reviews"},
    )


def test_openalex_fetch_by_issn_with_mocked_response() -> None:
    def opener(request, timeout):
        assert "sources/issn:1234-5678" in request.full_url
        payload = {
            "id": "https://openalex.org/S123",
            "display_name": "Example Journal",
            "issn": ["1234-5678"],
            "works_count": 100,
            "cited_by_count": 250,
            "summary_stats": {"h_index": 12},
            "counts_by_year": [
                {"year": 2026, "works_count": 10, "cited_by_count": 50},
                {"year": 2025, "works_count": 20, "cited_by_count": 40},
                {"year": 2024, "works_count": 30, "cited_by_count": 60},
                {"year": 2023, "works_count": 40, "cited_by_count": 80},
            ],
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "issn": {"print": "1234-5678", "online": ""},
        }
    )

    result = fetch_openalex_metadata(journal, now="2026-06-29", opener=opener)
    metrics = result.updates["prestige_metrics.openalex"]

    assert result.status == "matched"
    assert metrics["openalex_source_id"] == "S123"
    assert metrics["works_count"] == 100
    assert metrics["openalex_h_index"] == 12
    assert metrics["openalex_2yr_citation_rate"] == 3.0
    assert metrics["openalex_4yr_citation_rate"] == 2.3
    assert metrics["metric_year"] == 2026


def test_openalex_title_fallback_requires_exact_match() -> None:
    def opener(request, timeout):
        assert "search=Example%20Journal" in request.full_url
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/S123",
                    "display_name": "Example Journal Reviews",
                    "works_count": 10,
                    "cited_by_count": 20,
                    "counts_by_year": [],
                }
            ]
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    journal = JournalRecord.model_validate({"journal": "Example Journal"})

    result = fetch_openalex_metadata(journal, now="2026-06-29", opener=opener)

    assert result.status == "needs_review"


def test_openalex_metrics_from_source_computes_rates() -> None:
    metrics = openalex_metrics_from_source(
        {
            "id": "https://openalex.org/S999",
            "works_count": 60,
            "cited_by_count": 120,
            "summary_stats": {"h_index": 8},
            "counts_by_year": [
                {"year": 2025, "works_count": 10, "cited_by_count": 15},
                {"year": 2024, "works_count": 20, "cited_by_count": 45},
            ],
        },
        "2026-06-29",
    )

    assert metrics["openalex_source_id"] == "S999"
    assert metrics["openalex_2yr_citation_rate"] == 2.0
    assert metrics["last_checked"] == "2026-06-29"


def test_openalex_updates_do_not_overwrite_official_metrics(tmp_path: Path) -> None:
    journals_path = tmp_path / "journals.yaml"
    record = complete_record("Example Journal")
    record["prestige_metrics"]["impact_factor"] = 9.9
    journals_path.write_text(yaml.safe_dump([record]), encoding="utf-8")

    updated = apply_openalex_updates(
        journals_path,
        [
            OpenAlexResult(
                journal="Example Journal",
                status="matched",
                updates={
                    "prestige_metrics.openalex": {
                        "openalex_source_id": "S123",
                        "works_count": 10,
                        "cited_by_count": 20,
                        "counts_by_year": [],
                        "openalex_h_index": 3,
                        "openalex_2yr_citation_rate": None,
                        "openalex_4yr_citation_rate": None,
                        "metric_year": None,
                        "source_url": "https://openalex.org/S123",
                        "last_checked": "2026-06-29",
                    }
                },
            )
        ],
    )

    records = yaml.safe_load(journals_path.read_text(encoding="utf-8"))
    assert updated == 1
    assert records[0]["prestige_metrics"]["impact_factor"] == 9.9
    assert records[0]["prestige_metrics"]["openalex"]["openalex_source_id"] == "S123"


def test_scimago_float_parses_decimal_comma() -> None:
    assert parse_scimago_float("1,234") == 1.234


def test_scimago_match_uses_issn_before_title() -> None:
    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "publisher": "Example Publisher",
            "issn": {"print": "1234-5678", "online": ""},
        }
    )
    rows = [
        {
            "Sourceid": "1",
            "Title": "Different Title",
            "Issn": "12345678",
            "Publisher": "Example Publisher",
            "SJR": "1,234",
            "SJR Best Quartile": "Q1",
            "H index": "42",
        }
    ]

    assert match_scimago_row(journal, rows) == rows[0]


def test_scimago_short_title_fallback_requires_publisher() -> None:
    journal = JournalRecord.model_validate(
        {
            "journal": "Phage",
            "publisher": "Mary Ann Liebert",
        }
    )
    rows = [
        {
            "Sourceid": "1",
            "Title": "PHAGE: Therapy, Applications, and Research",
            "Issn": "26416549, 26416530",
            "Publisher": "Mary Ann Liebert Inc.",
            "SJR": "0,462",
            "SJR Best Quartile": "Q3",
            "H index": "17",
        }
    ]

    assert match_scimago_row(journal, rows) == rows[0]
    other = JournalRecord.model_validate({"journal": "Phage", "publisher": "Other"})
    assert match_scimago_row(other, rows) is None


def test_apply_scimago_metrics_preserves_jif_and_citescore(tmp_path: Path) -> None:
    journals_path = tmp_path / "journals.yaml"
    record = complete_record("Example Journal")
    record["issn"] = {"print": "1234-5678", "online": ""}
    record["prestige_metrics"]["impact_factor"] = 5.5
    record["prestige_metrics"]["cite_score"] = 6.6
    journals_path.write_text(yaml.safe_dump([record]), encoding="utf-8")
    scimago_path = tmp_path / "scimagojr_2025.csv"
    scimago_path.write_text(
        "Rank;Sourceid;Title;Type;Issn;Publisher;Open Access;"
        "Open Access Diamond;SJR;SJR Best Quartile;H index\n"
        '1;1;"Example Journal";journal;"12345678";"Example";No;No;1,234;Q1;42\n',
        encoding="utf-8",
    )

    result = apply_scimago_metrics(journals_path, scimago_path, metric_year=2025)
    records = yaml.safe_load(journals_path.read_text(encoding="utf-8"))
    metrics = records[0]["prestige_metrics"]

    assert result["matched"] == ["Example Journal"]
    assert metrics["impact_factor"] == 5.5
    assert metrics["cite_score"] == 6.6
    assert metrics["sjr"] == 1.234
    assert metrics["quartile"] == "Q1"
    assert metrics["h_index"] == 42
    assert metrics["metric_year"] == 2025
    assert "SCImago Journal Rank 2025 dataset" in metrics["metric_sources"][0]


def test_apc_parsing_is_conservative() -> None:
    assert parse_apc_amount("Article processing charge: USD 1,250") == (1250, "USD")
    assert parse_apc_amount("APC: USD 1000 or EUR 900") is None
    assert parse_apc_amount("No amount here") is None


def test_apc_parsing_skips_suspicious_pages(tmp_path: Path) -> None:
    cache = UrlCache(tmp_path / "cache")
    cache.load()
    page = tmp_path / "cache" / "pages" / "apc.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("Article processing charge: USD 1250", encoding="utf-8")
    cache.set(
        "https://example.org/apc",
        {
            "url": "https://example.org/apc",
            "status_code": 200,
            "content_path": str(page),
            "content_quality_flags": ["blocked_or_challenge_page"],
            "error": "",
        },
    )
    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "open_access": {
                "model": "",
                "apc": None,
                "currency": "",
                "url": "https://example.org/apc",
            },
        }
    )

    from journal_recommender.updating import check_apc

    result = check_apc(journal, cache, "2026-06-28")

    assert result.status == "blocked_or_suspicious"


def test_report_generation_contains_summary() -> None:
    report = UpdateReport(
        run_date="2026-06-28",
        trigger="local",
        journals_checked=1,
        url_results=[
            classify_url_result(
                "Example Journal",
                "https://example.org",
                {},
                {
                    "status_code": 403,
                    "error": "HTTP 403",
                    "content_quality_flags": [],
                },
                "2026-06-28",
            ),
            classify_url_result(
                "Example Journal",
                "https://example.org/suspicious",
                {},
                {
                    "status_code": 200,
                    "error": "",
                    "content_hash": "abc",
                    "content_quality_flags": ["very_short_body"],
                },
                "2026-06-28",
            ),
        ],
        crossref_results=[
            CrossrefResult(
                journal="Example Journal",
                status="matched",
                updates={"publisher": "Example Publisher"},
            )
        ],
        openalex_results=[
            OpenAlexResult(
                journal="Example Journal",
                status="matched",
                updates={
                    "prestige_metrics.openalex": {
                        "openalex_source_id": "S123",
                        "works_count": 10,
                        "cited_by_count": 20,
                        "metric_year": 2026,
                    }
                },
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
    assert "Blocked URLs: 1" in markdown
    assert "Suspicious fetched pages: 1" in markdown
    assert "Crossref records updated: 1" in markdown
    assert "OpenAlex records updated: 1" in markdown
    assert "S123" in markdown
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
        return FakeResponse(
            b"<html><body><h1>Example Journal</h1><p>This is a substantial "
            b"journal page with aims scope instructions and policy text for "
            b"testing a valid-looking publisher response.</p></body></html>"
        )

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


def test_index_record_contains_rich_structured_fields() -> None:
    journal = JournalRecord.model_validate(
        {
            "journal": "Example Journal",
            "abbreviated_title": "Ex J",
            "publisher": "Example Publisher",
            "issn": {"print": "1234-5678", "online": "8765-4321"},
            "article_types": ["Research Article"],
            "scope_tags": ["microbiome"],
            "manuscript_tags": ["metagenomics"],
            "suitable_for": ["shotgun metagenomics"],
            "less_suitable_for": ["clinical trial"],
            "data_policy": {"summary": "Data required.", "url": ""},
            "code_policy": {"summary": "Code encouraged.", "url": ""},
            "open_access": {
                "model": "hybrid",
                "apc": 1200,
                "currency": "USD",
                "url": "",
            },
            "editorial_notes": ["Specialist audience."],
        }
    )

    record = index_record(journal)

    assert record["issn"]["print"] == "1234-5678"
    assert record["article_types"] == ["Research Article"]
    assert record["open_access"]["apc"] == 1200
    assert "shotgun metagenomics" in record["text"]


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
