# Journal Recommender

Evidence-based journal recommendation tooling for microbiome, metagenomics,
microbial genomics, viromics, phage biology, microbial ecology, computational
biology, and related manuscripts.

The project separates journal fit from journal prestige and keeps curated facts
auditable through structured records and source evidence.

## Install

```bash
python -m pip install -e ".[dev]"
```

## Validate The Journal Database

```bash
python -m journal_recommender.cli validate-journals
```

The primary database is `data/journals.yaml`. Every journal must include the
complete structured record, even when fields are not yet curated. Empty strings,
empty lists, and `null` values are valid placeholders for unknown facts.

## Automated Journal Updates

The monthly GitHub Action in `.github/workflows/update-journal-database.yml`
checks curated journal URLs, records content hashes and content-quality flags,
queries Crossref by ISSN with a cautious exact-title fallback, conservatively
checks APC source pages, rebuilds a lightweight retrieval corpus, and writes
`reports/journal_database_changed.md`.

Run the same workflow locally with:

```bash
python -m journal_recommender.cli update-journals \
  --journals data/journals.yaml \
  --cache-dir data_raw/cache \
  --report reports/journal_database_changed.md \
  --delay-seconds 5

python -m journal_recommender.cli validate-journals data/journals.yaml

python -m journal_recommender.cli rebuild-index \
  --journals data/journals.yaml \
  --out data/index/journal_corpus.jsonl

python -m journal_recommender.cli report-changes \
  --cache-dir data_raw/cache \
  --report reports/journal_database_changed.md \
  --index data/index/journal_corpus.jsonl
```

Raw cached page bodies are stored under `data_raw/cache/pages/` and ignored by
git. Structured cache metadata, hashes, the report, and the JSONL index are safe
to review and commit.

The updater is intentionally conservative. It flags changed, blocked, or
suspicious publisher pages for human review instead of rewriting scope summaries
from HTML. APC values are reported as candidates only and are not written
automatically.

## Add A Journal

Add a complete structured record to `data/journals.yaml`, even when many fields
are unknown. Record official source URLs under `source_evidence` and leave
uncurated metrics, policies, APCs, and editorial notes empty rather than
guessing.

## Rank Journals For A Manuscript

Create a structured manuscript feature YAML file using the schema in
`docs/manuscript_feature_schema.md`, then validate and rank:

```bash
python -m journal_recommender.cli validate-manuscript \
  data/examples/microbiome_cohort_features.yaml

python -m journal_recommender.cli rank-journals \
  --manuscript data/examples/microbiome_cohort_features.yaml \
  --journals data/journals.yaml \
  --out reports/example_journal_recommendation.md
```

The first scoring engine is deterministic and transparent. It uses curated
journal tags, manuscript feature tags, policy summaries, practical constraints,
and conservative prestige tiers. It does not call an LLM or scrape publisher
pages during recommendation.

## Current Scope

This repository contains the journal schema, seed records, validation tests,
automated database-change checks, and a lightweight JSONL retrieval corpus.
It also includes a first deterministic manuscript-to-journal scoring engine.
Automated manuscript parsing from DOCX/PDF remains future work.
