"""Deterministic draft manuscript-feature generation from extracted text."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from journal_recommender.document_extract import ExtractedManuscript, extract_manuscript
from journal_recommender.manuscript import ManuscriptFeatures

SECTION_ORDER = [
    "Abstract",
    "Introduction",
    "Background",
    "Methods",
    "Materials and Methods",
    "Results",
    "Discussion",
    "Conclusion",
    "Data Availability",
    "Code Availability",
    "Software Availability",
]

SOFTWARE_TERMS = ("software", "tool", "pipeline", "workflow")
DATABASE_TERMS = ("database", "resource", "atlas", "catalog")
COHORT_TERMS = ("cohort", "longitudinal", "multi-site")
CLINICAL_TERMS = ("clinical cohort", "patient cohort", "hospital cohort")
ENVIRONMENTAL_TERMS = ("environmental survey", "survey", "wastewater", "soil", "marine")
MECHANISTIC_TERMS = ("mechanistic", "knockout", "perturbation", "causal")
VALIDATION_TERMS = ("validation", "experimental", "in vivo", "wet-lab")
DATASET_TERMS = (
    "data set",
    "dataset",
    "datasets",
    "benchmark dataset",
    "benchmark datasets",
)


def extract_and_draft_features(
    manuscript_path: str | Path,
    raw_bytes: bytes | None = None,
) -> tuple[ExtractedManuscript, ManuscriptFeatures]:
    extracted = extract_manuscript(manuscript_path, raw_bytes=raw_bytes)
    return extracted, draft_features_from_extracted(extracted)


def draft_features_from_extracted(extracted: ExtractedManuscript) -> ManuscriptFeatures:
    inference_text = build_inference_text(extracted)
    section_text = section_lookup(extracted.sections, SECTION_ORDER)

    data_types = infer_data_types(inference_text, section_text)
    field = infer_fields(inference_text, data_types)
    methods = infer_methods(inference_text, section_text)
    study_type = infer_study_type(inference_text, data_types, methods)
    novelty_type = infer_novelty_type(inference_text, data_types, methods, study_type)
    title = extracted.title.strip()
    abstract = extracted.abstract.strip()
    central_claim = infer_central_claim(title, abstract)
    organism_values = infer_organisms(inference_text)
    sample_type = infer_sample_types(inference_text)

    validation = infer_validation(inference_text, methods, study_type)
    code_available = infer_code_available(inference_text, section_text)
    data_available = infer_data_available(inference_text, section_text)
    mechanistic_depth = infer_mechanistic_depth(
        inference_text,
        study_type,
        methods,
    )
    editorial_risks = infer_editorial_risks(
        extracted,
        study_type=study_type,
        mechanistic_depth=mechanistic_depth,
        code_available=code_available,
        data_available=data_available,
    )

    features = ManuscriptFeatures.model_validate(
        {
            "title": title,
            "abstract": abstract,
            "central_claim": central_claim,
            "field": field,
            "organisms": organism_values,
            "sample_type": sample_type,
            "data_types": data_types,
            "methods": methods,
            "study_type": study_type,
            "novelty_type": novelty_type,
            "mechanistic_depth": mechanistic_depth,
            "cohort_size": infer_cohort_size(inference_text),
            "validation": validation,
            "code_available": code_available,
            "data_available": data_available,
            "clinical_relevance": infer_clinical_relevance(inference_text, field),
            "ecological_relevance": infer_ecological_relevance(inference_text, field),
            "bioinformatics_method_novelty": infer_bioinformatics_method_novelty(
                inference_text,
                methods,
            ),
            "likely_article_type": infer_likely_article_type(study_type, methods),
            "editorial_risks": editorial_risks,
            "constraints": {
                "open_access_required": None,
                "max_apc": None,
                "preferred_audience": infer_preferred_audience(field),
                "avoid_publishers": [],
            },
        }
    )
    return features


def manuscript_features_to_yaml(features: ManuscriptFeatures) -> str:
    data = features.model_dump(mode="python")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def build_inference_text(extracted: ExtractedManuscript) -> str:
    sections = [
        extracted.title,
        extracted.abstract,
    ]
    for name, text in extracted.sections.items():
        if name.lower() in {"references", "supplementary information"}:
            continue
        sections.append(text)
    return "\n".join(part for part in sections if part).lower()


def section_lookup(sections: dict[str, str], names: list[str]) -> str:
    collected: list[str] = []
    for name in names:
        for section_name, text in sections.items():
            if section_name.lower() == name.lower() and text:
                collected.append(text)
    return "\n".join(collected).lower()


def infer_data_types(text: str, section_text: str) -> list[str]:
    sources = f"{text}\n{section_text}"
    values: list[str] = []
    if any(
        phrase in sources
        for phrase in ["16s", "16s rrna", "amplicon", "amplicon sequencing"]
    ):
        values.append("16S rRNA amplicon")
    if "shotgun metagenom" in sources or (
        "metagenom" in sources and "shotgun" in sources
    ):
        values.append("shotgun metagenomics")
    if "metatranscriptom" in sources:
        values.append("metatranscriptomics")
    if "metabolom" in sources:
        values.append("metabolomics")
    if (
        "viral metagenom" in sources
        or "virome" in sources
        or "viral community" in sources
    ):
        values.append("viromics")
    if any(
        phrase in sources
        for phrase in [
            "metagenome-assembled genome",
            "metagenome assembled genome",
            "mag ",
            " mags",
        ]
    ):
        values.append("metagenome_assembled_genomes")
    if any(
        phrase in sources
        for phrase in [
            "isolate genome",
            "whole genome sequencing",
            "wgs",
            "genome sequencing",
            "comparative genomics",
        ]
    ):
        values.append("bacterial genomics")
    if "phage" in sources and "metagenom" in sources:
        values.append("viromics")
    if any(phrase in sources for phrase in ["long-read", "nanopore", "pacbio"]):
        values.append("long-read sequencing")
    if "rna-seq" in sources or "rnaseq" in sources or "transcriptomics" in sources:
        values.append("transcriptomics")
    return dedupe(values)


def infer_fields(text: str, data_types: list[str]) -> list[str]:
    values: list[str] = []
    sources = text
    if any(
        phrase in sources
        for phrase in ["microbiome", "microbiota", "microbial community"]
    ):
        values.append("microbiome")
    if any(phrase in sources for phrase in ["metagenom", "shotgun"]):
        values.append("metagenomics")
    if any(
        phrase in sources
        for phrase in ["genome sequencing", "comparative genomics", "mag"]
    ):
        values.append("microbial_genomics")
    if any(phrase in sources for phrase in ["virome", "viral metagenom", "viru"]):
        values.append("viromics")
    if any(phrase in sources for phrase in ["phage", "bacteriophage"]):
        values.append("phage_biology")
        if "metagenom" in sources or "virus" in sources:
            values.append("viromics")
    if any(
        phrase in sources
        for phrase in ["software", "pipeline", "workflow", "algorithm"]
    ):
        values.append("bioinformatics")
    if any(
        phrase in sources
        for phrase in ["clinical", "patient", "hospital", "infection", "pathogen"]
    ):
        values.append("clinical_microbiology")
    if any(
        phrase in sources
        for phrase in ["environment", "ecolog", "soil", "wastewater", "marine"]
    ):
        values.append("microbial_ecology")
    if any(
        phrase in sources
        for phrase in ["host-microbe", "host microbe", "host-associated"]
    ):
        values.append("host_microbe_interactions")
    if any(
        phrase in sources
        for phrase in ["machine learning", "deep learning", "computational"]
    ):
        values.append("computational_biology")
    if any(
        phrase in sources for phrase in ["database", "resource", "atlas", "catalog"]
    ):
        values.append("open_science")
    if "bioinformatics" in values or "software" in sources:
        values.append("bioinformatics")
    if "software" in sources or "pipeline" in sources:
        values.append("methods")
    return dedupe(values)


def infer_methods(text: str, section_text: str) -> list[str]:
    sources = f"{text}\n{section_text}"
    values: list[str] = []
    if "differential abundance" in sources:
        values.append("differential abundance")
    if any(
        phrase in sources
        for phrase in [
            "functional profiling",
            "functional analysis",
            "pathway analysis",
        ]
    ):
        values.append("functional profiling")
    if any(
        phrase in sources for phrase in ["assembly", "assembled", "genome assembly"]
    ):
        values.append("genome assembly")
    if any(phrase in sources for phrase in ["binning", "binned", "mag"]):
        values.append("binning")
        values.append("MAG reconstruction")
    if any(
        phrase in sources for phrase in ["taxonomic profiling", "taxonomic composition"]
    ):
        values.append("taxonomic profiling")
    if "phylogen" in sources:
        values.append("phylogenetics")
    if any(
        phrase in sources
        for phrase in ["machine learning", "random forest", "neural network"]
    ):
        values.append("machine learning")
    if any(
        phrase in sources
        for phrase in ["benchmark", "benchmarking", "comparison to existing tools"]
    ):
        values.append("benchmarking")
    if any(phrase in sources for phrase in ["software", "pipeline", "workflow"]):
        values.append("software development")
    if any(phrase in sources for phrase in ["database", "resource", "repository"]):
        values.append("database construction")
    if any(
        phrase in sources for phrase in ["network analysis", "co-expression network"]
    ):
        values.append("network analysis")
    if "comparative genomics" in sources:
        values.append("comparative genomics")
    if any(
        phrase in sources for phrase in ["host prediction", "host range prediction"]
    ):
        values.append("host prediction")
    if any(phrase in sources for phrase in ["phage annotation", "viral annotation"]):
        values.append("phage annotation")
    return dedupe(values)


def infer_study_type(text: str, data_types: list[str], methods: list[str]) -> str:
    if "review" in text and "review" not in methods:
        return "review"
    if re.search(r"\b(software|tool|pipeline|workflow)\b", text):
        return "software_tool"
    if any(term in text for term in ["genome resource", "genomic resource"]):
        return "genome_resource"
    if any(term in text for term in DATABASE_TERMS):
        return "database_resource"
    if any(term in text for term in ["methods paper", "methodological", "benchmark"]):
        return "methods_paper"
    if any(term in text for term in CLINICAL_TERMS):
        return "clinical_cohort"
    if any(term in text for term in COHORT_TERMS):
        return "cohort_study"
    if any(term in text for term in ENVIRONMENTAL_TERMS):
        return "environmental_survey"
    if any(term in text for term in MECHANISTIC_TERMS):
        return "mechanistic_study"
    if "genome" in text and any(
        term in text for term in ["resource", "atlas", "catalog"]
    ):
        return "genome_resource"
    return "descriptive_study"


def infer_novelty_type(
    text: str,
    data_types: list[str],
    methods: list[str],
    study_type: str,
) -> list[str]:
    values: list[str] = []
    if study_type == "clinical_cohort":
        values.append("clinical_cohort")
    if "clinical" in text or "patient" in text:
        values.append("clinical_cohort")
    if "multi-omic" in text or "multiomic" in text or "multi_omic" in text:
        values.append("multi_omics")
    if study_type in {"methods_paper"} or "methods" in methods:
        values.append("methods_paper")
    if study_type == "software_tool":
        values.append("software_tool")
    if study_type == "database_resource":
        values.append("database_resource")
    if study_type == "genome_resource":
        values.append("genome_resource")
    if "phage" in text:
        values.append("phage_genomics")
    if "virome" in text or "viral metagenom" in text:
        values.append("virome_analysis")
    if "benchmark" in methods or "benchmark" in text:
        values.append("benchmark")
    if any(term in text for term in ["mechanistic", "causal", "perturbation"]):
        values.append("mechanistic_study")
    return dedupe(values)


def infer_validation(
    text: str, methods: list[str], study_type: str
) -> dict[str, bool | None]:
    computational = True if any(phrase in text for phrase in SOFTWARE_TERMS) else None
    wet_lab = (
        True
        if any(
            phrase in text
            for phrase in [
                "wet-lab",
                "wet lab",
                "experimental validation",
                "in vivo",
                "qpcr",
                "culture",
            ]
        )
        else None
    )
    independent_dataset = (
        True
        if any(
            phrase in text
            for phrase in [
                "independent validation",
                "independent dataset",
                "external validation",
            ]
        )
        else None
    )
    if study_type in {"software_tool", "database_resource"} and computational is None:
        computational = True
    return {
        "wet_lab": wet_lab,
        "computational": computational,
        "independent_dataset": independent_dataset,
    }


def infer_code_available(text: str, section_text: str) -> bool | None:
    sources = f"{text}\n{section_text}"
    if any(
        phrase in sources
        for phrase in [
            "code available",
            "source code",
            "github",
            "repository",
            "software available",
        ]
    ):
        return True
    return None


def infer_data_available(text: str, section_text: str) -> bool | None:
    sources = f"{text}\n{section_text}"
    if any(
        phrase in sources
        for phrase in [
            "data available",
            "available data",
            "deposited in",
            "sra",
            "ena",
            "geo accession",
            "accession",
            "datasets are available",
            "dataset is available",
            "available in a repository",
            "available in repository",
            "available on github",
        ]
    ):
        return True
    return None


def infer_mechanistic_depth(
    text: str,
    study_type: str,
    methods: list[str],
) -> str:
    if study_type in {
        "software_tool",
        "database_resource",
        "genome_resource",
        "review",
    }:
        return "not_applicable"
    if any(term in text for term in MECHANISTIC_TERMS):
        return "high"
    if any(term in text for term in VALIDATION_TERMS):
        return "moderate"
    if methods and "machine learning" in methods:
        return "low"
    return "low"


def infer_central_claim(title: str, abstract: str) -> str:
    if abstract:
        sentence = first_sentence(abstract)
        return sentence or abstract[:200]
    if title:
        return title
    return ""


def infer_organisms(text: str) -> list[str]:
    values: list[str] = []
    if "human" in text:
        values.append("human")
    if "mouse" in text or "murine" in text:
        values.append("mouse")
    if "bacteria" in text or "microbiota" in text or "microbiome" in text:
        values.append("bacteria")
    if "archaea" in text:
        values.append("archaea")
    if "phage" in text or "bacteriophage" in text:
        values.append("bacteriophage")
    if "virus" in text or "viral" in text:
        values.append("virus")
    return dedupe(values)


def infer_sample_types(text: str) -> list[str]:
    values: list[str] = []
    if "stool" in text or "fecal" in text or "faecal" in text:
        values.append("stool")
    if "gut" in text:
        values.append("gut")
    if "wastewater" in text:
        values.append("wastewater")
    if "soil" in text:
        values.append("soil")
    if "marine" in text:
        values.append("marine")
    if "blood" in text:
        values.append("blood")
    if "sputum" in text:
        values.append("sputum")
    return dedupe(values)


def infer_cohort_size(text: str) -> int | None:
    match = re.search(r"\b(n|sample size)\s*=?\s*(\d{2,5})\b", text)
    if match:
        return int(match.group(2))
    return None


def infer_clinical_relevance(text: str, field: list[str]) -> str:
    if "clinical" in text or "patient" in text:
        return "clinical"
    if "microbiome" in field and "host_microbe_interactions" in field:
        return "host-associated"
    return ""


def infer_ecological_relevance(text: str, field: list[str]) -> str:
    if any(term in text for term in ENVIRONMENTAL_TERMS):
        return "environmental"
    if "host_microbe_interactions" in field:
        return "host-associated"
    return ""


def infer_bioinformatics_method_novelty(text: str, methods: list[str]) -> str:
    if "machine learning" in methods or "machine learning" in text:
        return "machine learning"
    if "software development" in methods:
        return "software development"
    if "benchmarking" in methods:
        return "benchmarking"
    return ""


def infer_likely_article_type(study_type: str, methods: list[str]) -> str:
    if study_type == "review":
        return "review"
    if study_type == "software_tool":
        return "software tool"
    if study_type == "database_resource":
        return "database resource"
    if study_type == "genome_resource":
        return "resource"
    if study_type in {"methods_paper"} or "software development" in methods:
        return "methods paper"
    return "research article"


def infer_preferred_audience(field: list[str]) -> str:
    if "bioinformatics" in field or "computational_biology" in field:
        return "specialist_audience"
    if "microbiome" in field or "phage_biology" in field:
        return "specialist_audience"
    return ""


def infer_editorial_risks(
    extracted: ExtractedManuscript,
    *,
    study_type: str,
    mechanistic_depth: str,
    code_available: bool | None,
    data_available: bool | None,
) -> list[str]:
    risks: list[str] = []
    if not extracted.abstract:
        risks.append("Abstract not detected; feature extraction may be incomplete.")
    if extracted.file_type == "pdf" and len(extracted.full_text.strip()) < 200:
        risks.append("PDF text extraction may be incomplete.")
    if mechanistic_depth != "high" and study_type not in {
        "review",
        "software_tool",
        "database_resource",
    }:
        risks.append("Mechanistic validation not detected.")
    if code_available is None:
        risks.append("Code availability statement not detected.")
    if data_available is None:
        risks.append("Data availability statement not detected.")
    risks.append(
        "Feature YAML was generated heuristically and should be reviewed "
        "before ranking."
    )
    return dedupe(risks)


def section_text(extracted: ExtractedManuscript, name: str) -> str:
    for section_name, text in extracted.sections.items():
        if section_name.lower() == name.lower():
            return text
    return ""


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def first_sentence(text: str) -> str:
    match = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
    return match[0].strip() if match else text.strip()
