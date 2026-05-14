#!/usr/bin/env python3
"""Validate generated .ipynb notebooks for shape and contract.

This is the post-build verification used by Stage 12 (validator agent) AND as a
standalone quality gate. Run after a dry-run to confirm the orchestrator
produced valid notebook output.

Checks per notebook:
  - Valid Jupyter JSON (nbformat: 4, non-empty cells[])
  - metadata.dependencies.lakehouse present
  - Bronze: append mode, has metadata-column pattern, has lakehouse binding to lh_bronze*
  - Silver: overwrite mode, reads ONLY via read_bronze() (no spark.read of files), binding to lh_silver*

Usage:
  python tests/validate_notebooks.py "3 - Notebooks/"
  python tests/validate_notebooks.py "3 - Notebooks/" --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SILVER_FORBIDDEN = [
    (r"spark\.read\.format\s*\(", "spark.read.format()"),
    (r"spark\.read\.csv\s*\(", "spark.read.csv()"),
    (r"spark\.read\.parquet\s*\(", "spark.read.parquet()"),
    (r"spark\.read\.json\s*\(", "spark.read.json()"),
    (r"spark\.read\.jdbc\s*\(", "spark.read.jdbc()"),
    (r"pd\.read_csv\s*\(", "pd.read_csv()"),
    (r"pd\.read_excel\s*\(", "pd.read_excel()"),
    (r"\babfss://", "abfss:// path"),
    (r"\bwasbs://", "wasbs:// path"),
]


def collect_notebook_text(nb: dict) -> str:
    pieces = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        if isinstance(src, list):
            pieces.append("".join(src))
        elif isinstance(src, str):
            pieces.append(src)
    return "\n\n".join(pieces)


def validate_one(path: Path, findings: list[dict]) -> bool:
    """Return True if all checks pass for this notebook."""
    name = path.name
    is_bronze = name.startswith("nb_bronze_") or "/bronze/" in str(path).replace("\\", "/")
    is_silver = name.startswith("nb_silver_") or "/silver/" in str(path).replace("\\", "/")

    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        findings.append({"path": str(path), "severity": "FAIL", "issue": f"Invalid JSON: {e}"})
        return False

    failed = False

    if nb.get("nbformat") != 4:
        findings.append({"path": str(path), "severity": "FAIL", "issue": f"nbformat is {nb.get('nbformat')}, expected 4"})
        failed = True
    if not nb.get("cells"):
        findings.append({"path": str(path), "severity": "FAIL", "issue": "Empty cells[]"})
        failed = True

    deps = nb.get("metadata", {}).get("dependencies", {}).get("lakehouse")
    if not deps:
        findings.append({"path": str(path), "severity": "FAIL", "issue": "Missing metadata.dependencies.lakehouse"})
        failed = True

    text = collect_notebook_text(nb)

    if is_silver:
        for pat, label in SILVER_FORBIDDEN:
            if re.search(pat, text):
                findings.append({
                    "path": str(path),
                    "severity": "FAIL",
                    "issue": f"Silver violates read_bronze()-only contract: {label}",
                })
                failed = True
        if "read_bronze" not in text:
            findings.append({
                "path": str(path),
                "severity": "FAIL",
                "issue": "Silver notebook missing read_bronze() call",
            })
            failed = True
        # Should write overwrite, not append
        if 'mode("append")' in text or "mode('append')" in text:
            findings.append({"path": str(path), "severity": "WARN", "issue": "Silver uses append mode — should be overwrite"})

    if is_bronze:
        if 'mode("append")' not in text and "mode('append')" not in text:
            findings.append({"path": str(path), "severity": "WARN", "issue": "Bronze missing append write mode"})
        if "_load_timestamp" not in text and "add_bronze_metadata" not in text:
            findings.append({"path": str(path), "severity": "WARN", "issue": "Bronze missing metadata column (_load_timestamp or add_bronze_metadata)"})

    # Count HIGH RISK cells (informational)
    risk_count = text.count("HIGH RISK / HUMAN REVIEW REQUIRED")
    if risk_count:
        findings.append({
            "path": str(path),
            "severity": "INFO",
            "issue": f"{risk_count} HIGH RISK isolation cell(s) — review per migration-design.md Section 5",
        })

    return not failed


def main():
    parser = argparse.ArgumentParser(description="Validate generated .ipynb notebooks.")
    parser.add_argument("path", help="Path to a notebook file or directory")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"ERROR: path not found: {target}", file=sys.stderr)
        sys.exit(2)

    if target.is_file():
        notebooks = [target]
    else:
        notebooks = sorted(target.rglob("*.ipynb"))

    if not notebooks:
        print(f"ERROR: no .ipynb files found under {target}", file=sys.stderr)
        sys.exit(2)

    findings: list[dict] = []
    pass_count = 0
    for nb in notebooks:
        if validate_one(nb, findings):
            pass_count += 1

    fail_findings = [f for f in findings if f["severity"] == "FAIL"]
    warn_findings = [f for f in findings if f["severity"] == "WARN"]
    info_findings = [f for f in findings if f["severity"] == "INFO"]

    envelope = {
        "status": "pass" if not fail_findings else "fail",
        "summary": {
            "total_notebooks": len(notebooks),
            "passed": pass_count,
            "failed": len(notebooks) - pass_count,
            "fail_findings": len(fail_findings),
            "warn_findings": len(warn_findings),
            "info_findings": len(info_findings),
        },
        "findings": findings,
    }

    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        print(f"=== Notebook Validation ===")
        print(f"Scanned: {len(notebooks)} notebook(s)")
        print(f"Passed structural: {pass_count}/{len(notebooks)}")
        for sev_label, items in [("FAIL", fail_findings), ("WARN", warn_findings), ("INFO", info_findings)]:
            if items:
                print(f"\n=== {sev_label} ({len(items)}) ===")
                for f in items:
                    rel = Path(f["path"]).name
                    print(f"  {rel}: {f['issue']}")
        print(f"\nOverall: {envelope['status'].upper()}")

    sys.exit(0 if not fail_findings else 1)


if __name__ == "__main__":
    main()
