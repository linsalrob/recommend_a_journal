"""
Rank the PDFs listed 
"""

from pathlib import Path
import subprocess
import yaml
__author__ = 'Rob Edwards'


repo = Path(".")
references = "references_short.yaml"
records = yaml.safe_load((repo / references).read_text())["validation_references"]

for rec in records:
    ref_id = rec["id"]
    features = repo / "features" / f"{ref_id}_deterministic_features.yaml"
    report = repo / "recommendations" / f"{ref_id}_deterministic.md"

    if not features.exists():
        print(f"SKIP missing features: {ref_id}")
        continue

    report.parent.mkdir(parents=True, exist_ok=True)

    print(f"Ranking {ref_id}")
    subprocess.run(
        [
            "python", "-m", "journal_recommender.cli", "rank-journals",
            "--manuscript", str(features),
            "--journals", "../data/journals.yaml",
            "--out", str(report),
        ],
        check=False,
    )




