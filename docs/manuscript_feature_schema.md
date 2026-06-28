# Manuscript Feature Schema

Structured manuscript feature files are YAML mappings validated by
`journal_recommender.manuscript.ManuscriptFeatures`.

```yaml
title: ""
abstract: ""
central_claim: ""
field: []
organisms: []
sample_type: []
data_types: []
methods: []
study_type: ""
novelty_type: []
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
editorial_risks: []
constraints:
  open_access_required: null
  max_apc: null
  preferred_audience: ""
  avoid_publishers: []
```
