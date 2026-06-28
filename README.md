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

## Add A Journal

Add a complete structured record to `data/journals.yaml`, even when many fields
are unknown. Record official source URLs under `source_evidence` and leave
uncurated metrics, policies, APCs, and editorial notes empty rather than
guessing.

## Current Scope

This initial repository contains the schema, seed journal records, and validation
tests. Manuscript parsing, scoring, and report generation are intentionally left
as explicit future implementation areas.
