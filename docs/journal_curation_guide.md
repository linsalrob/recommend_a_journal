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

## APC Sources

Prefer official journal APC pages, publisher open-access pages, or curated URLs
already present in `open_access.url`. Do not copy APCs from unofficial metric or
aggregator sites. If the report lists an APC as needing review, verify the
amount, currency, source URL, and access date before editing `data/journals.yaml`.

## Skipping Blocked URLs

If a publisher blocks automated checks or a page should remain human-curated
only, keep the URL for auditability but add `manually curated only` to the
matching `source_evidence` label or notes. The updater will skip source-evidence
URLs marked that way and will not attempt to bypass anti-bot protections.
