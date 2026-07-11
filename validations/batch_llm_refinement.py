"""

"""
from pathlib import Path
import subprocess
import yaml

repo = Path(".")
references = "references_short.yaml"
records = yaml.safe_load((repo / references).read_text())["validation_references"]

for rec in records:
    ref_id = rec["id"]
    pdf = repo / rec["pdf"]

    if not pdf.exists():
        print(f"SKIP missing PDF: {ref_id} -> {pdf}")
        continue

    deterministic = repo / "features" / f"{ref_id}_deterministic_features.yaml"
    llm_yaml = repo / "features" / f"{ref_id}_llm_refined_features.yaml"
    text_out = repo / "extracted" / f"{ref_id}_extracted_text.txt"
    report = repo / "recommendations" / f"{ref_id}_llm_refined.md"
    prompts = "../prompts/llm_feature_refinement.md"

    print(f"LLM refining {ref_id}")
    subprocess.run(
        [
            "python", "-m", "journal_recommender.cli", "refine-features-llm",
            "--manuscript", str(pdf),
            "--draft-out", str(deterministic),
            "--text-out", str(text_out),
            "--prompt-path", str(prompts),
            "--out", str(llm_yaml),
            "--model", "gpt-4.1-mini",
            "--verbose",
        ],
        check=False,
    )



    if not llm_yaml.exists():
        print(f"SKIP missing LLM features: {ref_id}")
        continue

    print(f"Ranking LLM-refined {ref_id}")
    subprocess.run(
        [
            "python", "-m", "journal_recommender.cli", "rank-journals",
            "--manuscript", str(llm_yaml),
            "--journals", "../data/journals.yaml",
            "--out", str(report),
        ],
        check=False,
    )
