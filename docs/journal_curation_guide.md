# Journal Curation Guide

Use official journal or publisher pages for aims, scope, author instructions,
open-access policies, and data or code policies. Leave unknown values empty or
`null`; do not infer APCs, metrics, article limits, or editorial preferences.

Every curated fact should have a matching entry in `source_evidence` with a URL,
access date, and short note.

## Automated Update Review

The automated updater runs monthly, on pushes to `main` or `master`, on new
GitHub releases, and by manual workflow dispatch. It uses conditional HTTP
requests where servers provide `ETag` or `Last-Modified`, waits between
publisher-page requests, and treats blocking or temporary server failures as
reportable events rather than hard failures.

Fetched pages are classified for basic quality. Empty pages, very short pages,
generic error pages, bot challenges, consent/redirect pages, and identical
content hashes across three or more unrelated URLs are reported as suspicious.
Do not use suspicious fetched content as evidence for APCs, scope summaries, or
policy updates.

To run it locally:

```bash
python -m journal_recommender.cli update-journals \
  --journals data/journals.yaml \
  --cache-dir data_raw/cache \
  --report reports/journal_database_changed.md \
  --delay-seconds 5
python -m journal_recommender.cli rebuild-index
python -m journal_recommender.cli report-changes
```

Review `reports/journal_database_changed.md` after each run. Changed or new URLs
mean the publisher page content hash changed; they do not mean the curated YAML
should be updated automatically. Open the official source page, confirm the
changed fact, then update the relevant structured field and `source_evidence`.

HTTP 403 and 429 responses are reported as blocked. If a URL blocks automated
checks for repeated runs, the report recommends manual curation. Do not attempt
to bypass publisher protections.

## APC Sources

Prefer official journal APC pages, publisher open-access pages, or curated URLs
already present in `open_access.url`. Do not copy APCs from unofficial metric or
aggregator sites. If the report lists an APC as needing review, verify the
amount, currency, source URL, and access date before editing `data/journals.yaml`.
The updater will not parse APCs from blocked, failed, or suspicious pages.

## ISSNs And Crossref

Prefer official journal pages, ISSN Portal, NLM Catalog, Crossref, or publisher
bibliographic pages for ISSNs. Add only print or online ISSNs that can be
confidently sourced; leave uncertain values blank. Crossref lookup uses ISSN
first. If no ISSN is present, exact normalized title matching can produce a
report note, but weak matches are marked `needs_review` and must not overwrite
curated fields.

## Skipping Blocked URLs

If a publisher blocks automated checks or a page should remain human-curated
only, keep the URL for auditability but add `manually curated only` to the
matching `source_evidence` label or notes. The updater will skip source-evidence
URLs marked that way and will not attempt to bypass anti-bot protections.

## Manual Source Workflow

Use the combined local workflow after saving blocked publisher pages manually:

```bash
python -m journal_recommender.cli process-manual-sources \
  --manifest data_manual/manifest.yaml \
  --journals data/journals.yaml \
  --suggestions data_manual/suggestions/manual_curation_suggestions.yaml \
  --review-report data_manual/suggestions/manual_curation_review.md \
  --manual-download-report reports/manual_download_queue.md \
  --manual-download-yaml data_manual/manual_download_queue.yaml
```

The command parses existing local files first, writes reviewable curation
suggestions, validates the journal database, rebuilds the index, and only then
generates the next manual-download queue. It never fetches publisher URLs.

Default mode does not edit `data/journals.yaml`. Use `--apply` only after
reviewing `data_manual/suggestions/manual_curation_suggestions.yaml` and
`data_manual/suggestions/manual_curation_review.md`.

Suggestions include field-level confidence. Regular `--apply` applies only
high-confidence fields from relevant sections, updates empty scalar fields,
appends list values without duplicates, preserves existing APCs, and adds
source-evidence entries for used manual sources. Use `--dry-run` to preview
changes. Use `--apply-low-confidence` only after reviewing medium/low-confidence
fields manually.

The parser intentionally ignores navigation, latest-article feeds,
related-journal lists, footer text, cookie notices, and publisher-wide
boilerplate for journal facts unless a relevant source section supports the
field.

PDF parsing is not implemented. Save pages as HTML or convert them to text.
