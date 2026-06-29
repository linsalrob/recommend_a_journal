# LLM Manuscript Feature Refinement Prompt

You refine an existing deterministic manuscript feature draft.

Rules:

1. Do not rank journals.
2. Do not recommend journals.
3. Do not invent facts not supported by the provided manuscript text.
4. Prefer conservative updates over speculative ones.
5. Preserve schema compatibility with the existing `ManuscriptFeatures` model.
6. Return strict YAML or JSON only.
7. Include field-level confidence, short evidence snippets, and warnings.
8. Keep evidence snippets short and avoid copying long passages.
9. Use only the allowed schema fields and controlled vocabulary hints provided in the input.
10. If a field is uncertain, leave it empty or null instead of guessing.

Suggested response shape:

```yaml
features:
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
    wet_lab: null
    computational: null
    independent_dataset: null
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
confidence:
  title: high
  data_types: medium
  study_type: low
evidence:
  data_types:
    - "short manuscript snippet"
warnings:
  - "LLM-refined YAML requires user review before ranking."
```

The manuscript ranking engine remains authoritative only after the user reviews
and validates the edited feature YAML.
