"""Conservative journal database update checks."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

from journal_recommender.schema import JournalRecord, validate_journal_file

USER_AGENT = (
    "journal-recommender/0.1 "
    "(https://github.com/; polite metadata checker; contact repository owner)"
)
NON_FATAL_STATUS_CODES = {403, 429, 500, 502, 503, 504}
URL_CACHE_FILE = "url_cache.json"
HASH_CACHE_FILE = "hashes.json"
LATEST_REPORT_FILE = "latest_update_report.json"


@dataclass
class UrlCheckResult:
    journal: str
    url: str
    status: str
    status_code: int | None
    previous_hash: str
    new_hash: str
    last_checked: str
    error: str = ""


@dataclass
class CrossrefResult:
    journal: str
    status: str
    updates: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass
class ApcResult:
    journal: str
    status: str
    source_url: str = ""
    previous_apc: int | float | None = None
    new_apc: int | float | None = None
    currency: str = ""
    note: str = ""


@dataclass
class UpdateReport:
    run_date: str
    trigger: str
    journals_checked: int
    url_results: list[UrlCheckResult] = field(default_factory=list)
    crossref_results: list[CrossrefResult] = field(default_factory=list)
    apc_results: list[ApcResult] = field(default_factory=list)
    index_status: str = "not rebuilt"

    @property
    def changed_urls(self) -> list[UrlCheckResult]:
        return [result for result in self.url_results if result.status == "changed"]

    @property
    def unchanged_urls(self) -> list[UrlCheckResult]:
        return [result for result in self.url_results if result.status == "unchanged"]

    @property
    def failed_urls(self) -> list[UrlCheckResult]:
        return [result for result in self.url_results if result.status == "failed"]

    @property
    def new_urls(self) -> list[UrlCheckResult]:
        return [result for result in self.url_results if result.status == "new"]

    @property
    def crossref_updates(self) -> list[CrossrefResult]:
        return [result for result in self.crossref_results if result.updates]

    @property
    def apc_updates(self) -> list[ApcResult]:
        return [result for result in self.apc_results if result.status == "updated"]

    @property
    def apc_review_needed(self) -> list[ApcResult]:
        return [
            result for result in self.apc_results if result.status == "needs_review"
        ]


class UrlCache:
    """JSON-backed URL cache with response metadata and content hashes."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.pages_dir = cache_dir / "pages"
        self.cache_path = cache_dir / URL_CACHE_FILE
        self.hashes_path = cache_dir / HASH_CACHE_FILE
        self.entries: dict[str, dict[str, Any]] = {}
        self.hashes: dict[str, str] = {}

    def load(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.entries = read_json_object(self.cache_path)
        self.hashes = read_json_object(self.hashes_path)

    def save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        write_json_object(self.cache_path, self.entries)
        write_json_object(self.hashes_path, self.hashes)

    def get(self, url: str) -> dict[str, Any]:
        return self.entries.get(url, {})

    def set(self, url: str, entry: dict[str, Any]) -> None:
        self.entries[url] = entry
        if entry.get("content_hash"):
            self.hashes[url] = entry["content_hash"]

    def content_path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.pages_dir / f"{digest}.html"


class PoliteFetcher:
    """HTTP fetcher with conditional requests, cache metadata, and throttling."""

    def __init__(
        self,
        cache: UrlCache,
        delay_seconds: float = 5.0,
        timeout_seconds: float = 20.0,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache = cache
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        self.sleeper = sleeper
        self.fetched_this_run: set[str] = set()

    def fetch(self, url: str, now: str) -> dict[str, Any]:
        cached = self.cache.get(url)
        if url in self.fetched_this_run:
            return {**cached, "from_run_cache": True}

        headers = {"User-Agent": USER_AGENT}
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

        request = Request(url, headers=headers)
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                status_code = response.getcode()
                body = response.read()
                content_hash = stable_content_hash(body)
                content_path = self.cache.content_path_for(url)
                content_path.write_bytes(body)
                entry = {
                    "url": url,
                    "last_checked": now,
                    "status_code": status_code,
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                    "content_hash": content_hash,
                    "content_path": str(content_path),
                    "error": "",
                }
                self.cache.set(url, entry)
        except HTTPError as exc:
            entry = self._entry_for_http_error(url, cached, exc, now)
        except URLError as exc:
            entry = self._entry_for_error(url, cached, str(exc.reason), now)
        except OSError as exc:
            entry = self._entry_for_error(url, cached, str(exc), now)

        self.fetched_this_run.add(url)
        if self.delay_seconds > 0:
            self.sleeper(self.delay_seconds)
        return entry

    def _entry_for_http_error(
        self,
        url: str,
        cached: dict[str, Any],
        exc: HTTPError,
        now: str,
    ) -> dict[str, Any]:
        if exc.code == 304:
            entry = {
                **cached,
                "url": url,
                "last_checked": now,
                "status_code": 304,
                "error": "",
            }
            self.cache.set(url, entry)
            return entry

        error = f"HTTP {exc.code}"
        if exc.code not in NON_FATAL_STATUS_CODES:
            error = f"{error}: {exc.reason}"
        return self._entry_for_error(url, cached, error, now, status_code=exc.code)

    def _entry_for_error(
        self,
        url: str,
        cached: dict[str, Any],
        error: str,
        now: str,
        status_code: int | None = None,
    ) -> dict[str, Any]:
        entry = {
            **cached,
            "url": url,
            "last_checked": now,
            "status_code": status_code,
            "error": error,
        }
        self.cache.set(url, entry)
        return entry


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def stable_content_hash(content: bytes | str) -> str:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="ignore")
    else:
        text = content
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_journal_urls(journal: JournalRecord) -> list[str]:
    manually_curated_only = {
        evidence.url
        for evidence in journal.source_evidence
        if evidence.url
        and "manually curated only"
        in " ".join([evidence.label, evidence.notes]).lower()
    }
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
        if not url or url in seen or url in manually_curated_only:
            continue
        seen.add(url)
        clean_urls.append(url)
    return clean_urls


def classify_url_result(
    journal: str,
    url: str,
    previous_entry: dict[str, Any],
    current_entry: dict[str, Any],
    now: str,
) -> UrlCheckResult:
    previous_hash = previous_entry.get("content_hash", "")
    new_hash = current_entry.get("content_hash", "")
    status_code = current_entry.get("status_code")
    error = current_entry.get("error", "")

    if error:
        status = "failed"
    elif status_code == 304:
        status = "unchanged"
        new_hash = previous_hash
    elif not previous_hash and new_hash:
        status = "new"
    elif previous_hash == new_hash:
        status = "unchanged"
    else:
        status = "changed"

    return UrlCheckResult(
        journal=journal,
        url=url,
        status=status,
        status_code=status_code,
        previous_hash=previous_hash,
        new_hash=new_hash,
        last_checked=now,
        error=error,
    )


def fetch_crossref_metadata(
    journal: JournalRecord,
    opener: Callable[..., Any] = urlopen,
    timeout_seconds: float = 20.0,
) -> CrossrefResult:
    issns = [journal.issn.print, journal.issn.online]
    issn = next((value for value in issns if value), "")
    if not issn:
        return CrossrefResult(
            journal=journal.journal,
            status="skipped",
            note="No ISSN available for Crossref lookup.",
        )

    url = f"https://api.crossref.org/journals/{quote(issn)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        return CrossrefResult(
            journal=journal.journal,
            status="failed",
            note=f"Crossref lookup failed: {exc}",
        )

    message = payload.get("message", {})
    if not crossref_matches_journal(journal, message):
        return CrossrefResult(
            journal=journal.journal,
            status="needs_review",
            note="Crossref response did not confidently match the journal record.",
        )

    updates: dict[str, Any] = {}
    notes = ["Matched by ISSN."]
    publisher = message.get("publisher", "")
    if publisher and not journal.publisher:
        updates["publisher"] = publisher
    title = message.get("title", "")
    if title and normalize_title(title) != normalize_title(journal.journal):
        notes.append(f"Crossref title variant: {title}")

    return CrossrefResult(
        journal=journal.journal,
        status="matched",
        updates=updates,
        note=" ".join(notes),
    )


def crossref_matches_journal(journal: JournalRecord, message: dict[str, Any]) -> bool:
    journal_issns = {
        value for value in [journal.issn.print, journal.issn.online] if value
    }
    crossref_issns = set(message.get("ISSN", []) or [])
    if journal_issns and journal_issns & crossref_issns:
        return True

    title = str(message.get("title", ""))
    return bool(title and normalize_title(title) == normalize_title(journal.journal))


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


APC_PATTERNS = [
    re.compile(r"\b(USD|US\$|\$)\s?([0-9][0-9,]*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\b(EUR|€)\s?([0-9][0-9,]*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\b(GBP|£)\s?([0-9][0-9,]*(?:\.\d+)?)", re.IGNORECASE),
]


def parse_apc_amount(text: str) -> tuple[int | float, str] | None:
    matches: list[tuple[float, str]] = []
    for pattern in APC_PATTERNS:
        for match in pattern.finditer(text):
            currency_token, amount_text = match.groups()
            amount = float(amount_text.replace(",", ""))
            currency = normalize_currency(currency_token)
            matches.append((amount, currency))

    unique_matches = sorted(set(matches))
    if len(unique_matches) != 1:
        return None

    amount, currency = unique_matches[0]
    if amount.is_integer():
        return int(amount), currency
    return amount, currency


def normalize_currency(token: str) -> str:
    token = token.upper()
    if token in {"US$", "$"}:
        return "USD"
    if token == "€":
        return "EUR"
    if token == "£":
        return "GBP"
    return token


def check_apc(
    journal: JournalRecord,
    cache: UrlCache,
    now: str,
) -> ApcResult:
    source_url = journal.open_access.url or ""
    if not source_url:
        return ApcResult(
            journal=journal.journal,
            status="skipped",
            note="No open-access/APC URL available.",
        )

    entry = cache.get(source_url)
    content_path = entry.get("content_path", "")
    if not content_path or not Path(content_path).exists():
        return ApcResult(
            journal=journal.journal,
            status="needs_review",
            source_url=source_url,
            note="APC source was not fetched; manual review required.",
        )

    content = Path(content_path).read_text(encoding="utf-8", errors="ignore")
    parsed = parse_apc_amount(content)
    if not parsed:
        return ApcResult(
            journal=journal.journal,
            status="needs_review",
            source_url=source_url,
            note="APC not updated automatically; manual review required.",
        )

    amount, currency = parsed
    if journal.open_access.apc is not None and journal.open_access.apc != amount:
        return ApcResult(
            journal=journal.journal,
            status="needs_review",
            source_url=source_url,
            previous_apc=journal.open_access.apc,
            new_apc=amount,
            currency=currency,
            note="Existing APC differs from parsed value; manual review required.",
        )

    if journal.open_access.apc == amount and journal.open_access.currency == currency:
        return ApcResult(
            journal=journal.journal,
            status="unchanged",
            source_url=source_url,
            previous_apc=journal.open_access.apc,
            new_apc=amount,
            currency=currency,
            note="Parsed APC matches existing value.",
        )

    return ApcResult(
        journal=journal.journal,
        status="candidate",
        source_url=source_url,
        previous_apc=journal.open_access.apc,
        new_apc=amount,
        currency=currency,
        note=f"Possible APC found on {now}; manual review required before updating.",
    )


def apply_crossref_updates(
    journals_path: Path,
    crossref_results: list[CrossrefResult],
) -> int:
    updates_by_journal = {
        result.journal: result.updates
        for result in crossref_results
        if result.updates
    }
    if not updates_by_journal:
        return 0

    records = load_raw_yaml(journals_path)
    updated = 0
    for record in records:
        journal_name = record.get("journal")
        updates = updates_by_journal.get(journal_name)
        if not updates:
            continue
        for field_name, value in updates.items():
            if field_name in record and not record[field_name]:
                record[field_name] = value
                updated += 1

    if updated:
        with journals_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(records, handle, sort_keys=False, allow_unicode=True)
    return updated


def run_journal_update(
    journals_path: Path,
    cache_dir: Path,
    report_path: Path,
    delay_seconds: float = 5.0,
    trigger: str = "local",
    check_crossref: bool = True,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> UpdateReport:
    now = datetime.now(UTC).date().isoformat()
    journals = validate_journal_file(journals_path)
    cache = UrlCache(cache_dir)
    cache.load()
    fetcher = PoliteFetcher(
        cache=cache,
        delay_seconds=delay_seconds,
        opener=opener,
        sleeper=sleeper,
    )

    url_results: list[UrlCheckResult] = []
    for journal in journals:
        for url in collect_journal_urls(journal):
            previous_entry = dict(cache.get(url))
            current_entry = fetcher.fetch(url, now)
            url_results.append(
                classify_url_result(
                    journal=journal.journal,
                    url=url,
                    previous_entry=previous_entry,
                    current_entry=current_entry,
                    now=now,
                )
            )

    crossref_results = []
    if check_crossref:
        crossref_results = [
            fetch_crossref_metadata(journal, opener=opener) for journal in journals
        ]
        apply_crossref_updates(journals_path, crossref_results)

    apc_results = [check_apc(journal, cache, now) for journal in journals]
    cache.save()

    report = UpdateReport(
        run_date=now,
        trigger=trigger,
        journals_checked=len(journals),
        url_results=url_results,
        crossref_results=crossref_results,
        apc_results=apc_results,
    )
    write_report_json(report, cache_dir / LATEST_REPORT_FILE)
    write_change_report(report, report_path)
    return report


def write_change_report(report: UpdateReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_change_report(report), encoding="utf-8")


def write_report_json(report: UpdateReport, path: Path) -> None:
    data = {
        "run_date": report.run_date,
        "trigger": report.trigger,
        "journals_checked": report.journals_checked,
        "url_results": [result.__dict__ for result in report.url_results],
        "crossref_results": [result.__dict__ for result in report.crossref_results],
        "apc_results": [result.__dict__ for result in report.apc_results],
        "index_status": report.index_status,
    }
    write_json_object(path, data)


def read_report_json(path: Path) -> UpdateReport:
    data = read_json_object(path)
    return UpdateReport(
        run_date=str(data.get("run_date", "")),
        trigger=str(data.get("trigger", "")),
        journals_checked=int(data.get("journals_checked", 0)),
        url_results=[
            UrlCheckResult(**result) for result in data.get("url_results", [])
        ],
        crossref_results=[
            CrossrefResult(**result) for result in data.get("crossref_results", [])
        ],
        apc_results=[ApcResult(**result) for result in data.get("apc_results", [])],
        index_status=str(data.get("index_status", "not rebuilt")),
    )


def generate_report_from_latest(
    cache_dir: Path,
    report_path: Path,
    index_path: Path | None = None,
) -> UpdateReport:
    report = read_report_json(cache_dir / LATEST_REPORT_FILE)
    if index_path is not None:
        if index_path.exists():
            report.index_status = f"Rebuilt index at `{index_path}`."
        else:
            report.index_status = f"Index file `{index_path}` was not found."
    write_report_json(report, cache_dir / LATEST_REPORT_FILE)
    write_change_report(report, report_path)
    return report


def render_change_report(report: UpdateReport) -> str:
    lines = [
        "# Journal Database Changed Report",
        "",
        f"- Run date: {report.run_date}",
        f"- Workflow trigger: {report.trigger}",
        "",
        "## Summary",
        "",
        f"- Journals checked: {report.journals_checked}",
        f"- URLs checked: {len(report.url_results)}",
        f"- Changed URLs: {len(report.changed_urls)}",
        f"- New URLs: {len(report.new_urls)}",
        f"- Unchanged URLs: {len(report.unchanged_urls)}",
        f"- Failed URLs: {len(report.failed_urls)}",
        f"- Crossref records updated: {len(report.crossref_updates)}",
        f"- APCs updated: {len(report.apc_updates)}",
        f"- APCs needing review: {len(report.apc_review_needed)}",
        "",
        "## Changed Pages",
        "",
        render_url_table(report.changed_urls + report.new_urls),
        "",
        "## Failed Or Blocked URLs",
        "",
        render_url_table(report.failed_urls),
        "",
        "## Crossref Updates",
        "",
        render_crossref_table(report.crossref_results),
        "",
        "## APC Updates And Review Needed",
        "",
        render_apc_table(report.apc_results),
        "",
        "## Index Rebuild Status",
        "",
        report.index_status,
        "",
        "## Recommended Manual Follow-Up",
        "",
        "- Review changed or new publisher pages before editing curated summaries.",
        "- Manually verify APC candidates before writing amounts into journals.yaml.",
        "- Check failed URLs for publisher blocking, moved pages, "
        "or temporary downtime.",
        "- Mark URLs as manually curated only if automated checks should skip "
        "them later.",
        "",
    ]
    return "\n".join(lines)


def render_url_table(results: list[UrlCheckResult]) -> str:
    if not results:
        return "No entries."
    lines = [
        "| Journal | Status | HTTP | URL | Previous hash | New hash | Error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            f"{escape_cell(result.journal)} | "
            f"{result.status} | "
            f"{result.status_code or ''} | "
            f"{escape_cell(result.url)} | "
            f"{short_hash(result.previous_hash)} | "
            f"{short_hash(result.new_hash)} | "
            f"{escape_cell(result.error)} |"
        )
    return "\n".join(lines)


def render_crossref_table(results: list[CrossrefResult]) -> str:
    if not results:
        return "No Crossref lookups were run."
    lines = [
        "| Journal | Status | Updates | Note |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        updates = ", ".join(sorted(result.updates)) if result.updates else ""
        lines.append(
            "| "
            f"{escape_cell(result.journal)} | "
            f"{result.status} | "
            f"{escape_cell(updates)} | "
            f"{escape_cell(result.note)} |"
        )
    return "\n".join(lines)


def render_apc_table(results: list[ApcResult]) -> str:
    if not results:
        return "No APC checks were run."
    lines = [
        "| Journal | Status | Source | Previous APC | New APC | Currency | Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            f"{escape_cell(result.journal)} | "
            f"{result.status} | "
            f"{escape_cell(result.source_url)} | "
            f"{result.previous_apc if result.previous_apc is not None else ''} | "
            f"{result.new_apc if result.new_apc is not None else ''} | "
            f"{result.currency} | "
            f"{escape_cell(result.note)} |"
        )
    return "\n".join(lines)


def short_hash(value: str) -> str:
    return value[:12] if value else ""


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def load_raw_yaml(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, list) else []
