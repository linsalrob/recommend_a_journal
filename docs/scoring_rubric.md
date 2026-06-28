# Scoring Rubric

Default weights:

```yaml
scope_alignment: 0.30
significance_fit: 0.25
audience_match: 0.15
methods_and_policy_fit: 0.10
prestige: 0.10
practical_constraints: 0.10
```

Prestige must be scored separately from manuscript fit. A higher-prestige journal
with weak scope alignment should not outrank a credible journal with strong fit
unless an aspirational strategy is explicitly requested.

## First-Pass Deterministic Scoring

The current scorer is transparent and tag-based. It does not use an LLM or live
publisher scraping.

- `scope_alignment`: overlap between manuscript-derived tags and curated journal
  `scope_tags` plus `manuscript_tags`.
- `significance_fit`: whether the manuscript novelty level matches the journal's
  breadth and selectivity.
- `audience_match`: fit between broad or specialist audience signals.
- `methods_and_policy_fit`: compatibility for methods, software, data, code, and
  resource manuscripts.
- `prestige`: a conservative heuristic prestige tier used only as one component.
- `practical_constraints`: open-access needs, APC limits where curated, and
  publisher avoidance.

The report separates best strategic target, current-manuscript fit, safest
credible journal, aspirational journal, and journals not recommended.
