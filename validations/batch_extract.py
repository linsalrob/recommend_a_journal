from pathlib import Path
import subprocess
import yaml

repo = Path(".")
refs_yaml = repo / "references.yaml"
records = yaml.safe_load(refs_yaml.read_text())["validation_references"]

for rec in records:
    ref_id = rec["id"]
    pdf = repo / rec["pdf"]

    if not pdf.exists():
        print(f"SKIP missing PDF: {ref_id} -> {pdf}")
        continue

    out_yaml = repo / "validation" / "features" / f"{ref_id}_deterministic_features.yaml"
    out_text = repo / "validation" / "extracted" / f"{ref_id}_extracted_text.txt"

    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_text.parent.mkdir(parents=True, exist_ok=True)

    print(f"Extracting {ref_id}")
    subprocess.run(
        [
            "python", "-m", "journal_recommender.cli", "extract-features",
            "--manuscript", str(pdf),
            "--out", str(out_yaml),
            "--text-out", str(out_text),
        ],
        check=False,
    )
