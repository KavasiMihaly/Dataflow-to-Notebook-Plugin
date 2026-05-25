#!/usr/bin/env python3
"""Regression tests for the M conversion risk catalog.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.

Covers:
  - All 30 RISK-NN sections exist (RISK-01 through RISK-30) — catches drift
    between the catalog and the m-query-analyst / orchestrator references
  - Every RISK-NN section has a Detection line (regex/string the analyst
    scans for)
  - Every RISK-NN section has at least one fenced code block (PySpark
    mitigation or TODO marker)
  - The catalog header count matches the actual RISK-NN count
  - The m-query-analyst and orchestrator agent.md files reference the same
    count as the catalog header
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
CATALOG = ROOT / "reference" / "m-conversion-risk-catalog.md"
ANALYST = ROOT / "agents" / "m-query-analyst" / "agent.md"
ORCHESTRATOR = ROOT / "agents" / "fabric-migration-orchestrator" / "agent.md"

EXPECTED_RISK_COUNT = 30
FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


def test_all_30_risks_present() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    headings = re.findall(r"^## RISK-(\d+) ", text, flags=re.MULTILINE)
    found_ids = sorted({int(n) for n in headings})
    expected_ids = list(range(1, EXPECTED_RISK_COUNT + 1))
    missing = set(expected_ids) - set(found_ids)
    extra = set(found_ids) - set(expected_ids)
    _check(
        f"Catalog has all RISK-01..RISK-{EXPECTED_RISK_COUNT:02d} headings",
        not missing and not extra,
        detail=f"missing={sorted(missing)} extra={sorted(extra)}",
    )


def test_every_risk_has_detection_line() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    sections = re.split(r"^## RISK-(\d+) ", text, flags=re.MULTILINE)
    # split produces [preamble, "01", body01, "02", body02, ...]
    for i in range(1, len(sections), 2):
        risk_num = sections[i]
        body = sections[i + 1]
        _check(
            f"RISK-{risk_num} has a **Detection:** line",
            "**Detection:**" in body,
            detail="missing detection regex",
        )


def test_every_risk_has_mitigation_content() -> None:
    """Every RISK section must document the mitigation somehow — either a fenced
    code block (most entries), an inline code-mapping table (RISK-08 style), or
    a prose recommendation containing inline code (RISK-09, RISK-14 style)."""
    text = CATALOG.read_text(encoding="utf-8")
    sections = re.split(r"^## RISK-(\d+) ", text, flags=re.MULTILINE)
    for i in range(1, len(sections), 2):
        risk_num = sections[i]
        body = sections[i + 1]
        section_text = re.split(r"\n---\n", body, maxsplit=1)[0]
        has_fence = bool(re.search(r"```(python|m)\b", section_text))
        # Mapping table: `| M | PySpark |` header
        has_mapping_table = bool(re.search(r"\|\s*M\s*\|\s*PySpark\s*\|", section_text))
        # Prose recommendation: `**PySpark` (any variant) anywhere
        has_pyspark_callout = bool(re.search(r"\*\*PySpark", section_text))
        _check(
            f"RISK-{risk_num} documents a mitigation (code block, mapping table, or PySpark callout)",
            has_fence or has_mapping_table or has_pyspark_callout,
            detail="no ```python/m block, `| M | PySpark |` table, or **PySpark callout found",
        )


def test_catalog_header_count_matches() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    # Header sentence: "documents the N known Power Query M patterns"
    m = re.search(r"documents the (\d+) known Power Query M patterns", text)
    _check(
        "Catalog header mentions correct count",
        m is not None and int(m.group(1)) == EXPECTED_RISK_COUNT,
        detail=f"header says {m.group(1) if m else '?'}, expected {EXPECTED_RISK_COUNT}",
    )


def test_analyst_reference_count_matches() -> None:
    text = ANALYST.read_text(encoding="utf-8")
    m = re.search(r"the (\d+) known risk patterns", text)
    _check(
        "m-query-analyst references correct risk count",
        m is not None and int(m.group(1)) == EXPECTED_RISK_COUNT,
        detail=f"agent.md says {m.group(1) if m else '?'}, expected {EXPECTED_RISK_COUNT}",
    )


def test_orchestrator_reference_count_matches() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    m = re.search(r"the (\d+) known risk patterns", text)
    _check(
        "fabric-migration-orchestrator references correct risk count",
        m is not None and int(m.group(1)) == EXPECTED_RISK_COUNT,
        detail=f"agent.md says {m.group(1) if m else '?'}, expected {EXPECTED_RISK_COUNT}",
    )


def main() -> int:
    test_all_30_risks_present()
    test_every_risk_has_detection_line()
    test_every_risk_has_mitigation_content()
    test_catalog_header_count_matches()
    test_analyst_reference_count_matches()
    test_orchestrator_reference_count_matches()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
