"""Deterministic manuscript-to-journal scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from journal_recommender.manuscript import ManuscriptFeatures, load_manuscript_features
from journal_recommender.schema import JournalRecord, validate_journal_file

DEFAULT_WEIGHTS = {
    "scope_alignment": 0.30,
    "significance_fit": 0.25,
    "audience_match": 0.15,
    "methods_and_policy_fit": 0.10,
    "prestige": 0.10,
    "practical_constraints": 0.10,
}

PRESTIGE_TIERS = {
    "Nature": 100,
    "Science": 100,
    "Cell": 96,
    "Nature Microbiology": 88,
    "Nature Biotechnology": 88,
    "Nature Methods": 88,
    "Nature Communications": 82,
    "Science Advances": 80,
    "Cell Host & Microbe": 82,
    "Genome Biology": 78,
    "Genome Research": 76,
    "PNAS": 78,
    "Microbiome": 74,
    "ISME Journal": 74,
    "Bioinformatics": 72,
    "Briefings in Bioinformatics": 72,
    "PLOS Computational Biology": 70,
    "Journal of Virology": 68,
    "mBio": 68,
    "mSystems": 64,
    "NAR Genomics and Bioinformatics": 64,
    "GigaScience": 62,
}

TAG_SYNONYMS = {
    "16s": "microbiome",
    "16s_rrna": "microbiome",
    "amplicon": "microbiome",
    "bacteriophage": "phage_biology",
    "benchmarking": "benchmark",
    "clinical": "clinical_microbiology",
    "database": "database",
    "gut_microbiome": "microbiome",
    "machine_learning": "machine_learning",
    "mag": "metagenome_assembled_genomes",
    "mags": "metagenome_assembled_genomes",
    "metagenomic": "metagenomics",
    "metagenomics": "metagenomics",
    "microbial_genomics": "microbial_genomics",
    "microbiome": "microbiome",
    "multiomics": "multi_omics",
    "multi_omics": "multi_omics",
    "phage": "phage_biology",
    "phage_genomics": "phage_genomics",
    "software": "software_tool",
    "software_tool": "software_tool",
    "tool": "software_tool",
    "virome": "virome_analysis",
    "viromics": "viromics",
}

BROAD_JOURNALS = {"Nature", "Science", "Cell", "PNAS", "Science Advances"}
ASPIRATIONAL_JOURNALS = BROAD_JOURNALS | {
    "Nature Microbiology",
    "Nature Biotechnology",
    "Nature Methods",
    "Cell Host & Microbe",
    "Genome Biology",
}


@dataclass
class JournalScore:
    journal: str
    total_score: float
    component_scores: dict[str, float]
    matched_tags: list[str] = field(default_factory=list)
    missing_or_weak_tags: list[str] = field(default_factory=list)
    rationale_bullets: list[str] = field(default_factory=list)
    desk_rejection_risks: list[str] = field(default_factory=list)
    evidence_fields_used: list[str] = field(default_factory=list)
    category: str = "ranked"
    main_reason: str = ""
    main_risk: str = ""


@dataclass
class RecommendationSet:
    manuscript: ManuscriptFeatures
    scores: list[JournalScore]
    best_strategic_target: JournalScore
    best_current_fit: JournalScore
    safest_credible_journal: JournalScore
    aspirational_journal: JournalScore
    not_recommended: list[JournalScore]


def score_journals(
    manuscript: ManuscriptFeatures,
    journals: list[JournalRecord],
    weights: dict[str, float] | None = None,
) -> RecommendationSet:
    active_weights = weights or DEFAULT_WEIGHTS
    manuscript_tags = derive_manuscript_tags(manuscript)
    scores = [
        score_single_journal(manuscript, manuscript_tags, journal, active_weights)
        for journal in journals
    ]
    scores.sort(key=lambda score: score.total_score, reverse=True)

    best_current = max(
        scores,
        key=lambda score: (
            score.component_scores["scope_alignment"]
            + score.component_scores["methods_and_policy_fit"],
            score.total_score,
        ),
    )
    safest = max(
        [score for score in scores if score.total_score >= 45] or scores,
        key=lambda score: (
            -len(score.desk_rejection_risks),
            score.component_scores["scope_alignment"],
            score.total_score,
        ),
    )
    aspirational = max(
        [score for score in scores if score.journal in ASPIRATIONAL_JOURNALS] or scores,
        key=lambda score: (
            score.component_scores["prestige"],
            score.component_scores["scope_alignment"],
        ),
    )
    strategic = max(
        scores,
        key=lambda score: (
            score.total_score,
            score.component_scores["significance_fit"],
            score.component_scores["scope_alignment"],
        ),
    )
    not_recommended = [
        score
        for score in scores
        if score.total_score < 35 or len(score.desk_rejection_risks) >= 3
    ][:10]

    assign_categories(scores, strategic, best_current, safest, aspirational)
    return RecommendationSet(
        manuscript=manuscript,
        scores=scores,
        best_strategic_target=strategic,
        best_current_fit=best_current,
        safest_credible_journal=safest,
        aspirational_journal=aspirational,
        not_recommended=not_recommended,
    )


def score_single_journal(
    manuscript: ManuscriptFeatures,
    manuscript_tags: set[str],
    journal: JournalRecord,
    weights: dict[str, float],
) -> JournalScore:
    journal_tags = set(journal.scope_tags) | set(journal.manuscript_tags)
    matched_tags = sorted(manuscript_tags & journal_tags)
    weak_tags = sorted(manuscript_tags - journal_tags)

    component_scores = {
        "scope_alignment": scope_alignment_score(manuscript_tags, journal_tags),
        "significance_fit": significance_fit_score(manuscript, journal),
        "audience_match": audience_match_score(manuscript, journal),
        "methods_and_policy_fit": methods_policy_score(manuscript, journal),
        "prestige": prestige_score(journal),
        "practical_constraints": practical_constraints_score(manuscript, journal),
    }
    total = sum(component_scores[key] * weights[key] for key in weights)
    risks = desk_risks(manuscript, journal, component_scores)
    rationale = rationale_bullets(journal, matched_tags, component_scores)

    return JournalScore(
        journal=journal.journal,
        total_score=round(total, 1),
        component_scores={
            key: round(value, 1) for key, value in component_scores.items()
        },
        matched_tags=matched_tags,
        missing_or_weak_tags=weak_tags[:8],
        rationale_bullets=rationale,
        desk_rejection_risks=risks,
        evidence_fields_used=evidence_fields(journal),
        main_reason=rationale[0] if rationale else "No strong positive evidence.",
        main_risk=risks[0] if risks else "No major desk-rejection risk from tags.",
    )


def derive_manuscript_tags(manuscript: ManuscriptFeatures) -> set[str]:
    raw_values: list[str] = []
    raw_values.extend(manuscript.field)
    raw_values.extend(manuscript.data_types)
    raw_values.extend(manuscript.methods)
    raw_values.extend(manuscript.sample_type)
    raw_values.extend(manuscript.novelty_type)
    raw_values.append(manuscript.study_type)
    raw_values.append(manuscript.likely_article_type)
    raw_values.append(manuscript.bioinformatics_method_novelty)
    raw_values.append(manuscript.clinical_relevance)
    raw_values.append(manuscript.ecological_relevance)

    tags = {normalise_tag(value) for value in raw_values if normalise_tag(value)}
    text = " ".join(raw_values).lower()
    if "cohort" in text:
        tags.add("cohort_study")
    if "clinical" in text:
        tags.add("clinical_cohort")
        tags.add("clinical_microbiology")
    if "environment" in text or "ecolog" in text:
        tags.add("microbial_ecology")
        tags.add("environmental_survey")
    if re.search(r"\b(software|tool|tools)\b", text):
        tags.add("software_tool")
        tags.add("bioinformatics")
    if "database" in text or "resource" in text:
        tags.add("database_resource")
    if "method" in text or "pipeline" in text:
        tags.add("methods_paper")
    if "phage" in text or "bacteriophage" in text:
        tags.add("phage_biology")
        tags.add("phage_genomics")
    if "virome" in text or "virus" in text:
        tags.add("viromics")
        tags.add("virome_analysis")
    if "broad" in text or "high_concept" in text:
        tags.add("broad_interest")
        tags.add("high_concept_discovery")
    return tags


def normalise_tag(value: str) -> str:
    tag = value.strip().lower().replace("-", "_").replace(" ", "_")
    return TAG_SYNONYMS.get(tag, tag)


def scope_alignment_score(manuscript_tags: set[str], journal_tags: set[str]) -> float:
    if not manuscript_tags:
        return 35.0
    overlap = manuscript_tags & journal_tags
    score = 25 + 75 * (len(overlap) / len(manuscript_tags))
    if {"broad_science", "broad_interest"} & journal_tags and len(overlap) >= 2:
        score += 8
    return min(score, 100.0)


def significance_fit_score(
    manuscript: ManuscriptFeatures,
    journal: JournalRecord,
) -> float:
    tags = set(journal.manuscript_tags) | set(journal.scope_tags)
    manuscript_tags = derive_manuscript_tags(manuscript)
    score = 50.0
    if "high_concept_discovery" in manuscript_tags and "broad_interest" in tags:
        score += 35
    if "broad_interest" in manuscript_tags and journal.journal in BROAD_JOURNALS:
        score += 25
    if journal.journal in BROAD_JOURNALS and "broad_interest" not in manuscript_tags:
        score -= 30
    if "descriptive_study" in manuscript_tags and journal.journal in BROAD_JOURNALS:
        score -= 20
    if "methods_paper" in manuscript_tags and "methods" in tags:
        score += 20
    if "software_tool" in manuscript_tags and "software_tool" in tags:
        score += 20
    if "specialist_audience" in tags and journal.journal not in BROAD_JOURNALS:
        score += 8
    return clamp(score)


def audience_match_score(
    manuscript: ManuscriptFeatures,
    journal: JournalRecord,
) -> float:
    preferred = manuscript.constraints.preferred_audience
    tags = set(journal.manuscript_tags) | set(journal.scope_tags)
    manuscript_tags = derive_manuscript_tags(manuscript)
    score = 55.0
    if preferred and preferred in tags:
        score += 25
    if "specialist_audience" in tags and "broad_interest" not in manuscript_tags:
        score += 20
    if "broad_interest" in tags and "broad_interest" in manuscript_tags:
        score += 20
    if journal.journal in BROAD_JOURNALS and "broad_interest" not in manuscript_tags:
        score -= 25
    return clamp(score)


def methods_policy_score(
    manuscript: ManuscriptFeatures,
    journal: JournalRecord,
) -> float:
    tags = set(journal.manuscript_tags) | set(journal.scope_tags)
    manuscript_tags = derive_manuscript_tags(manuscript)
    score = 50.0
    if {"software_tool", "methods_paper", "benchmark"} & manuscript_tags:
        if {"software", "software_tool", "methods", "bioinformatics"} & tags:
            score += 30
        else:
            score -= 20
    if {"database_resource", "resource", "genome_resource"} & manuscript_tags:
        if {"database", "resource", "genomics", "open_science"} & tags:
            score += 20
    if (
        manuscript.code_available is False
        and {"software_tool", "methods_paper"} & manuscript_tags
    ):
        score -= 25
    if manuscript.data_available is False:
        score -= 15
    if journal.data_policy.summary:
        score += 5
    if journal.code_policy.summary and manuscript.code_available is not None:
        score += 5
    return clamp(score)


def prestige_score(journal: JournalRecord) -> float:
    if journal.journal in PRESTIGE_TIERS:
        return float(PRESTIGE_TIERS[journal.journal])
    if "broad_science" in journal.scope_tags:
        return 75.0
    if "specialist_audience" in journal.manuscript_tags:
        return 55.0
    return 50.0


def practical_constraints_score(
    manuscript: ManuscriptFeatures,
    journal: JournalRecord,
) -> float:
    score = 75.0
    constraints = manuscript.constraints
    if journal.publisher in constraints.avoid_publishers:
        score -= 70
    if constraints.open_access_required is True:
        if journal.open_access.model in {"fully_open_access", "open_access"}:
            score += 15
        elif journal.open_access.model == "hybrid":
            score -= 5
        else:
            score -= 20
    if constraints.max_apc is not None and journal.open_access.apc is not None:
        if journal.open_access.apc > constraints.max_apc:
            score -= 40
    return clamp(score)


def desk_risks(
    manuscript: ManuscriptFeatures,
    journal: JournalRecord,
    components: dict[str, float],
) -> list[str]:
    risks: list[str] = []
    manuscript_tags = derive_manuscript_tags(manuscript)
    if components["scope_alignment"] < 45:
        risks.append("Weak tag-level scope alignment.")
    if journal.journal in BROAD_JOURNALS and "broad_interest" not in manuscript_tags:
        risks.append("Broad journal likely requires wider conceptual significance.")
    if "software_tool" in manuscript_tags and "software" not in journal.scope_tags:
        risks.append("Software/method novelty may not be central to this journal.")
    if (
        "descriptive_study" in manuscript_tags
        and journal.journal in ASPIRATIONAL_JOURNALS
    ):
        risks.append("Descriptive study may need stronger mechanism or novelty.")
    risks.extend(manuscript.editorial_risks[:2])
    return risks


def rationale_bullets(
    journal: JournalRecord,
    matched_tags: list[str],
    components: dict[str, float],
) -> list[str]:
    bullets: list[str] = []
    if matched_tags:
        bullets.append(f"Matches curated tags: {', '.join(matched_tags[:6])}.")
    if components["scope_alignment"] >= 70:
        bullets.append("Strong scope alignment from curated journal profile.")
    if components["methods_and_policy_fit"] >= 70:
        bullets.append("Methods, data, or code expectations are compatible.")
    if components["prestige"] >= 80:
        bullets.append(
            "High-prestige outlet; use as aspirational unless fit is strong."
        )
    if not bullets:
        bullets.append("Limited positive evidence from current structured fields.")
    return bullets


def evidence_fields(journal: JournalRecord) -> list[str]:
    fields = []
    if journal.scope_tags:
        fields.append("scope_tags")
    if journal.manuscript_tags:
        fields.append("manuscript_tags")
    if journal.suitable_for:
        fields.append("suitable_for")
    if journal.less_suitable_for:
        fields.append("less_suitable_for")
    if journal.source_evidence:
        fields.append("source_evidence")
    return fields


def assign_categories(
    scores: list[JournalScore],
    strategic: JournalScore,
    current: JournalScore,
    safest: JournalScore,
    aspirational: JournalScore,
) -> None:
    for score in scores:
        score.category = "ranked"
    strategic.category = "best strategic target"
    current.category = "best current-manuscript fit"
    safest.category = "safest credible journal"
    aspirational.category = "aspirational journal"


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def rank_journals_from_files(
    manuscript_path: Path,
    journals_path: Path,
    report_path: Path | None = None,
) -> RecommendationSet:
    manuscript = load_manuscript_features(manuscript_path)
    journals = validate_journal_file(journals_path)
    recommendations = score_journals(manuscript, journals)
    if report_path is not None:
        write_recommendation_report(recommendations, report_path)
    return recommendations


def write_recommendation_report(
    recommendations: RecommendationSet,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_recommendation_report(recommendations), encoding="utf-8")


def render_recommendation_report(recommendations: RecommendationSet) -> str:
    manuscript = recommendations.manuscript
    shortlist = recommendations.scores[:10]
    lines = [
        "# Journal Recommendation Report",
        "",
        "## Manuscript Diagnosis",
        "",
        manuscript_diagnosis(manuscript),
        "",
        "## Extracted Manuscript Features",
        "",
        render_features(manuscript),
        "",
        "## Top Recommendation",
        "",
        render_score_summary(recommendations.scores[0]),
        "",
        "## Ranked Shortlist",
        "",
        "| Rank | Journal | Category | Score | Main reason | Main risk |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for rank, score in enumerate(shortlist, start=1):
        lines.append(
            f"| {rank} | {score.journal} | {score.category} | "
            f"{score.total_score:.1f} | {escape_cell(score.main_reason)} | "
            f"{escape_cell(score.main_risk)} |"
        )
    lines.extend(
        [
            "",
            "## Best Strategic Target",
            "",
            render_score_summary(recommendations.best_strategic_target),
            "",
            "## Best Current-Manuscript Fit",
            "",
            render_score_summary(recommendations.best_current_fit),
            "",
            "## Safest Credible Journal",
            "",
            render_score_summary(recommendations.safest_credible_journal),
            "",
            "## Aspirational Journal",
            "",
            render_score_summary(recommendations.aspirational_journal),
            "",
            "## Journals Not Recommended",
            "",
            render_not_recommended(recommendations.not_recommended),
            "",
            "## Required Reframing For Higher-Tier Journals",
            "",
            reframing_advice(manuscript),
            "",
            "## Evidence Used",
            "",
            render_evidence(shortlist),
            "",
        ]
    )
    return "\n".join(lines)


def manuscript_diagnosis(manuscript: ManuscriptFeatures) -> str:
    tags = sorted(derive_manuscript_tags(manuscript))
    if not tags:
        return "The manuscript feature file contains limited topical signal."
    return (
        "The manuscript appears to be a "
        f"{manuscript.study_type or 'structured'} study with signals for "
        f"{', '.join(tags[:8])}. Ranking emphasizes journal fit over prestige."
    )


def render_features(manuscript: ManuscriptFeatures) -> str:
    values: dict[str, Any] = manuscript.model_dump()
    lines = []
    for key in [
        "title",
        "field",
        "data_types",
        "methods",
        "study_type",
        "novelty_type",
        "likely_article_type",
        "editorial_risks",
    ]:
        lines.append(f"- {key}: {values[key]}")
    return "\n".join(lines)


def render_score_summary(score: JournalScore) -> str:
    bullets = "\n".join(f"- {bullet}" for bullet in score.rationale_bullets)
    risks = "\n".join(f"- {risk}" for risk in score.desk_rejection_risks)
    if not risks:
        risks = "- No major desk-rejection risk from current tags."
    return (
        f"**{score.journal}** scored {score.total_score:.1f}/100.\n\n"
        f"{bullets}\n\nRisks:\n{risks}"
    )


def render_not_recommended(scores: list[JournalScore]) -> str:
    if not scores:
        return "No journals were categorically excluded by the first-pass rules."
    return "\n".join(
        f"- {score.journal}: {score.main_risk} (score {score.total_score:.1f})."
        for score in scores
    )


def reframing_advice(manuscript: ManuscriptFeatures) -> str:
    tags = derive_manuscript_tags(manuscript)
    advice = []
    if "broad_interest" not in tags:
        advice.append(
            "Clarify the field-wide conceptual advance before targeting broad "
            "science journals."
        )
    if "descriptive_study" in tags:
        advice.append("Add mechanism, validation, or generalizable insight.")
    if "software_tool" in tags and manuscript.code_available is not True:
        advice.append("Make code availability and benchmarking explicit.")
    if not advice:
        advice.append(
            "Emphasize novelty, validation, and audience fit in the abstract."
        )
    return "\n".join(f"- {item}" for item in advice)


def render_evidence(scores: list[JournalScore]) -> str:
    lines = []
    for score in scores:
        lines.append(
            f"- {score.journal}: {', '.join(score.evidence_fields_used) or 'none'}; "
            f"matched tags: {', '.join(score.matched_tags) or 'none'}."
        )
    return "\n".join(lines)


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
