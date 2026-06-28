# AGENTS.md

## Project purpose

This repository builds and maintains a journal-recommendation system for bioinformatics, microbiome, metagenomics, microbial genomics, viromics, phage biology, microbial ecology, computational biology, and related manuscripts.

The system should ingest curated journal information, maintain structured journal profiles, retrieve aims/scope and author-instruction evidence, parse uploaded manuscripts, and recommend the most appropriate journals based on both prestige and manuscript fit.

The goal is not to recommend the highest-impact journal by default. The goal is to recommend the best strategic journal target, with transparent evidence and reasoning.

## Core principles

1. Be evidence-based.

   * Do not invent journal scope, article limits, APCs, metrics, data policies, or editorial preferences.
   * Every journal fact should be traceable to a source URL, citation, or manually curated note.

2. Separate journal prestige from journal fit.

   * Prestige metrics are useful but should not dominate the recommendation.
   * Fit should consider manuscript topic, article type, novelty, data type, audience, methodological depth, and editorial risk.

3. Prefer structured data over free text.

   * Journal metadata should be stored in machine-readable YAML, JSON, or CSV.
   * Free-text journal profiles are useful, but structured fields are required for scoring.

4. Make outputs auditable.

   * Journal recommendations should explain which evidence was used.
   * Ranking scores should be reproducible from stored metadata and scoring rules.

5. Avoid fragile scraping.

   * Prefer official APIs, manually curated source URLs, cached HTML/text, and stable publisher pages.
   * If scraping is used, keep it polite, slow, cached, and easy to disable.

6. Maintain scientific nuance.

   * A descriptive microbiome manuscript, a method paper, a genome-resource paper, a clinical cohort study, and a mechanistic microbial ecology paper should not be ranked using the same assumptions.
   * The system should be candid about desk-rejection risk.

## Expected repository structure

Use or create this structure unless there is a strong reason to change it.

```text
journal-recommender/
  AGENTS.md
  README.md
  pyproject.toml
  data/
    journals.yaml
    journal_metrics.csv
    source_urls.csv
    controlled_vocabularies.yaml
  data_raw/
    html/
    pdf/
    text/
  docs/
    journal_profiles/
    scoring_rubric.md
    manuscript_feature_schema.md
  prompts/
    manuscript_parser.md
    journal_ranker.md
    editorial_triage.md
    presubmission_enquiry.md
  src/
    journal_recommender/
      __init__.py
      ingest/
      parsing/
      retrieval/
      scoring/
      reporting/
      cli.py
  tests/
    test_journal_schema.py
    test_scoring.py
    test_parsing.py
  reports/
  scripts/
```

## Journal database requirements

The primary journal database should live at:

```text
data/journals.yaml
```

Each journal record should include, where available:

```yaml
- journal: ""
  abbreviated_title: ""
  publisher: ""
  issn:
    print: ""
    online: ""
  homepage_url: ""
  aims_scope_url: ""
  author_instructions_url: ""
  article_types:
    - ""
  scope_tags:
    - ""
  manuscript_tags:
    - ""
  suitable_for:
    - ""
  less_suitable_for:
    - ""
  data_policy:
    summary: ""
    url: ""
  code_policy:
    summary: ""
    url: ""
  open_access:
    model: ""
    apc: null
    currency: ""
    url: ""
  prestige_metrics:
    impact_factor: null
    cite_score: null
    sjr: null
    h_index: null
    quartile: ""
    metric_year: null
    metric_sources:
      - ""
  editorial_notes:
    - ""
  example_papers:
    - title: ""
      doi: ""
      url: ""
      reason_relevant: ""
  source_evidence:
    - label: ""
      url: ""
      accessed: ""
      notes: ""
  last_checked: ""
```

Do not remove fields merely because they are empty. Empty fields are acceptable placeholders if the source has not yet been curated.

## Initial journal set

Prioritise journals relevant to the following manuscript types:

* microbiome studies;
* shotgun metagenomics;
* 16S rRNA amplicon studies;
* metatranscriptomics;
* viromics;
* phage genomics;
* bacterial genomics;
* microbial ecology;
* clinical microbiology;
* computational biology;
* bioinformatics methods;
* genome resources;
* database/resource papers;
* machine learning for microbial genomics;
* multi-omics studies.

Seed the database with journals including, but not limited to:

* Nature
* Science
* Cell
* Nature Microbiology
* Nature Biotechnology
* Nature Methods
* Nature Communications
* Science Advances
* Cell Host & Microbe
* Genome Biology
* Genome Research
* PNAS
* Microbiome
* ISME Journal
* ISME Communications
* mBio
* mSystems
* Microbiology Spectrum
* Microbial Genomics
* Environmental Microbiology
* Environmental Microbiome
* Applied and Environmental Microbiology
* FEMS Microbiology Ecology
* Bioinformatics
* Briefings in Bioinformatics
* PLOS Computational Biology
* NAR Genomics and Bioinformatics
* GigaScience
* BMC Bioinformatics
* PeerJ Computer Science
* Virus Evolution
* Journal of Virology
* Viruses
* Phage
* Virology

Add additional journals when they are clearly relevant.

## Manuscript feature extraction

The system should parse manuscripts and extract structured features such as:

```yaml
title: ""
abstract: ""
central_claim: ""
field:
  - ""
organisms:
  - ""
sample_type:
  - ""
data_types:
  - ""
methods:
  - ""
study_type: ""
novelty_type:
  - ""
mechanistic_depth: ""
cohort_size: null
validation:
  wet_lab: false
  computational: false
  independent_dataset: false
code_available: null
data_available: null
clinical_relevance: ""
ecological_relevance: ""
bioinformatics_method_novelty: ""
likely_article_type: ""
editorial_risks:
  - ""
```

The parser should distinguish between:

* biology-first discovery papers;
* methods papers;
* software/tool papers;
* database/resource papers;
* genome announcements or resource notes;
* clinical cohort studies;
* mechanistic experimental studies;
* descriptive microbial ecology studies;
* phage/virome studies;
* translational microbiome studies.

## Journal scoring model

Implement a transparent scoring system. A reasonable default weighting is:

```yaml
scope_alignment: 0.30
significance_fit: 0.25
audience_match: 0.15
methods_and_policy_fit: 0.10
prestige: 0.10
practical_constraints: 0.10
```

The scoring model should produce:

1. best strategic target;
2. best current-manuscript fit;
3. safest credible journal;
4. aspirational journal;
5. journals not recommended, with reasons.

Do not collapse these categories into a single simplistic ranking.

## Recommendation report

For each uploaded manuscript, the final report should include:

1. one-paragraph manuscript diagnosis;
2. extracted manuscript features;
3. top recommended journal;
4. ranked shortlist of 5–10 journals;
5. rationale for each recommendation;
6. evidence from journal scope/instructions;
7. desk-rejection risks;
8. changes required to target a higher-tier journal;
9. journals to avoid;
10. suggested title/abstract reframing, where useful;
11. optional presubmission enquiry draft.

The report should be candid and specific. Avoid vague statements such as “this is a good fit for many journals.”

## Prestige metrics

Prestige metrics may include:

* Journal Impact Factor;
* CiteScore;
* SCImago Journal Rank;
* journal h-index;
* quartile;
* field-specific reputation notes.

These metrics should be stored separately and labelled with their year and source.

Do not treat Impact Factor, h-index, or CiteScore as interchangeable.

Do not over-optimise for prestige. A high-prestige journal with poor scope alignment should rank below a slightly less prestigious journal with strong scope alignment unless the user explicitly asks for an aspirational strategy.

## Source handling

When collecting journal information:

1. Record the source URL.
2. Record the access date.
3. Prefer official journal or publisher pages for aims/scope and author instructions.
4. Prefer recognised metric sources for journal metrics.
5. If information is manually curated, mark it as manually curated.
6. If a value is uncertain, use `null` and add a note rather than guessing.

## Coding standards

Use Python 3.11 or newer.

Prefer:

* `pydantic` for schemas and validation;
* `pyyaml` or `ruamel.yaml` for YAML;
* `pandas` for tabular journal/metric exports;
* `typer` or `argparse` for command-line tools;
* `pytest` for tests;
* `ruff` for linting;
* `black` or `ruff format` for formatting.

Avoid large, unnecessary frameworks in the first implementation.

## Suggested commands

Create or maintain commands similar to:

```bash
python -m journal_recommender.cli validate-journals
python -m journal_recommender.cli ingest-journal --journal "Microbiome"
python -m journal_recommender.cli parse-manuscript manuscript.docx
python -m journal_recommender.cli rank-journals manuscript_features.yaml
python -m journal_recommender.cli generate-report manuscript.docx --out reports/report.md
pytest
ruff check .
ruff format .
```

If commands differ, update this file and the README.

## Testing requirements

Add tests for:

* journal YAML schema validation;
* required fields;
* scoring reproducibility;
* missing metric handling;
* manuscript feature extraction on small fixture files;
* report generation;
* ranking behaviour for obvious cases.

For example:

* a strong microbiome cohort paper should rank `Microbiome` or `ISME Journal` highly;
* a software/tool paper should rank `Bioinformatics`, `NAR Genomics and Bioinformatics`, `GigaScience`, or `PLOS Computational Biology` more highly than biology-only journals;
* a phage genomics paper should not be forced into microbiome journals unless host-associated microbiome data are central.

## Data ethics and copyright

Do not store full copyrighted journal pages unless the repository is private and this is permitted by the source terms.

Prefer storing:

* short summaries;
* structured metadata;
* source URLs;
* access dates;
* short quotations only where necessary and legally appropriate.

Do not redistribute proprietary metric data if the licence does not permit it.

## Security and privacy

Uploaded manuscripts may be confidential.

Do not commit private manuscripts, reviewer comments, grant applications, or unpublished data to the repository.

Use `data_raw/private/`, `manuscripts/`, and `reports/private/` only if these paths are gitignored.

The `.gitignore` should include:

```text
manuscripts/
reports/private/
data_raw/private/
.env
*.docx
*.pdf
```

unless a file is intentionally added as a public fixture.

## Documentation

Maintain:

```text
README.md
docs/scoring_rubric.md
docs/manuscript_feature_schema.md
docs/journal_curation_guide.md
```

The README should explain:

* what the project does;
* how to install it;
* how to add a journal;
* how to validate the journal database;
* how to run a manuscript recommendation;
* how to interpret the scores.

## Behaviour expected from coding agents

When working on this repository:

1. Inspect existing files before making changes.
2. Preserve the structured schema unless explicitly asked to change it.
3. Add tests when adding functionality.
4. Do not invent journal data.
5. Mark unknown values as `null`.
6. Keep changes small and reviewable.
7. Prefer readable, boring code over clever code.
8. Update documentation when behaviour changes.
9. Never commit secrets, API keys, private manuscripts, or proprietary journal-metric exports.
10. Explain assumptions in commit messages or PR summaries.

## Definition of done

A task is complete only when:

* relevant code or data files have been updated;
* journal records validate against the schema;
* tests pass or failures are clearly explained;
* source URLs are recorded for curated journal facts;
* README or docs are updated if user-facing behaviour changed;
* generated outputs are placed in an appropriate ignored or reports directory.

