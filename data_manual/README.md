# Manual Journal Sources

This directory records publisher pages downloaded manually in a browser when
automated access is blocked, suspicious, or incomplete.

Recommended workflow:

```bash
python -m journal_recommender.cli process-manual-sources \
  --manifest data_manual/manifest.yaml \
  --journals data/journals.yaml \
  --suggestions data_manual/suggestions/manual_curation_suggestions.yaml \
  --review-report data_manual/suggestions/manual_curation_review.md \
  --manual-download-report reports/manual_download_queue.md \
  --manual-download-yaml data_manual/manual_download_queue.yaml

# review suggestions and manual_curation_review.md

python -m journal_recommender.cli process-manual-sources \
  --manifest data_manual/manifest.yaml \
  --journals data/journals.yaml \
  --suggestions data_manual/suggestions/manual_curation_suggestions.yaml \
  --review-report data_manual/suggestions/manual_curation_review.md \
  --manual-download-report reports/manual_download_queue.md \
  --manual-download-yaml data_manual/manual_download_queue.yaml \
  --apply
```

Suggestions are section-aware and include field-level confidence plus a review
status. Regular `--apply` applies only high-confidence fields; use `--dry-run`
to preview and `--apply-low-confidence` only after manual review.

Raw downloaded pages should be saved under `data_manual/pages/`. Extracted text
can be written to `data_manual/extracted/` with `--text-out-dir`; both paths are
ignored by git.

Use HTML, HTM, TXT, or Markdown files. PDF parsing is not implemented; convert
PDFs to text or save the web page as HTML first.
