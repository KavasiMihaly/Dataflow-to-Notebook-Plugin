#!/usr/bin/env python3
"""Slice 7 — engine-aware risk catalog + docs regression tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.

Covers the 3 Slice-7 tests:
  1. test_catalog_parses_with_engine_column — the catalog still satisfies the
     existing structural rules from test_risk_catalog.py (all 30 RISK-NN
     headings, a Detection line each, a mitigation each, header count). The
     engine annotation must NOT break any of those.
  2. test_every_risk_has_engine_note — every RISK-NN section carries a Python
     applicability note (one of: ease / worsen / N-A / unchanged) so the
     catalog is engine-aware end-to-end.
  3. test_readme_documents_toggle — the README documents the `notebook_engine`
     toggle: the decision matrix, both engine values, AND the Python engine
     limitations (no env vars / Environment item, single-node memory, some
     Delta features unsupported).

Run from repo root: python tests/test_catalog_engine_addendum.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
CATALOG = ROOT / "reference" / "m-conversion-risk-catalog.md"
README = ROOT / "README.md"

EXPECTED_RISK_COUNT = 30

# The Python applicability marker the catalog uses per RISK section.
# Format chosen (documented in the Slice 7 plan outcome note): a single
# `**Python:** <marker> — <rationale>` line inside every RISK-NN section,
# where <marker> is one of these four keywords.
PYTHON_NOTE_LABEL = "**Python:**"
VALID_MARKERS = ("ease", "worsen", "N-A", "unchanged")

FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


def _risk_sections(text: str) -> list[tuple[str, str]]:
    """Return [(risk_num, section_body_up_to_next_---), ...]."""
    parts = re.split(r"^## RISK-(\d+) ", text, flags=re.MULTILINE)
    out: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        risk_num = parts[i]
        body = parts[i + 1]
        section_text = re.split(r"\n---\n", body, maxsplit=1)[0]
        out.append((risk_num, section_text))
    return out


# --- Test 1: existing structural rules still hold with the engine note ------

def test_catalog_parses_with_engine_column() -> None:
    """Duplicates the key structural checks from test_risk_catalog.py so the
    engine annotation cannot silently break the catalog contract."""
    text = CATALOG.read_text(encoding="utf-8")

    # (a) all 30 RISK-NN headings
    headings = re.findall(r"^## RISK-(\d+) ", text, flags=re.MULTILINE)
    found_ids = sorted({int(n) for n in headings})
    expected_ids = list(range(1, EXPECTED_RISK_COUNT + 1))
    _check(
        "Catalog still has all RISK-01..RISK-30 headings",
        found_ids == expected_ids,
        detail=f"found={found_ids}",
    )

    sections = _risk_sections(text)

    # (b) Detection line each
    missing_detection = [n for n, body in sections if "**Detection:**" not in body]
    _check(
        "Every RISK section still has a **Detection:** line",
        not missing_detection,
        detail=f"missing in RISK-{missing_detection}",
    )

    # (c) mitigation each (fenced code block OR `| M | PySpark |` table OR
    #     `**PySpark` callout) — same rule as test_risk_catalog.py
    missing_mitigation = []
    for n, body in sections:
        has_fence = bool(re.search(r"```(python|m)\b", body))
        has_mapping_table = bool(re.search(r"\|\s*M\s*\|\s*PySpark\s*\|", body))
        has_pyspark_callout = bool(re.search(r"\*\*PySpark", body))
        if not (has_fence or has_mapping_table or has_pyspark_callout):
            missing_mitigation.append(n)
    _check(
        "Every RISK section still documents a mitigation",
        not missing_mitigation,
        detail=f"missing in RISK-{missing_mitigation}",
    )

    # (d) header count sentence
    m = re.search(r"documents the (\d+) known Power Query M patterns", text)
    _check(
        "Catalog header still mentions the correct count",
        m is not None and int(m.group(1)) == EXPECTED_RISK_COUNT,
        detail=f"header says {m.group(1) if m else '?'}",
    )


# --- Test 2: every risk has a Python applicability note --------------------

def test_every_risk_has_engine_note() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    sections = _risk_sections(text)
    for risk_num, body in sections:
        has_label = PYTHON_NOTE_LABEL in body
        # The marker keyword must appear on the same line as the label.
        marker_ok = False
        if has_label:
            for line in body.splitlines():
                if line.lstrip().startswith(PYTHON_NOTE_LABEL):
                    marker_ok = any(mk in line for mk in VALID_MARKERS)
                    break
        _check(
            f"RISK-{risk_num} has a Python applicability note "
            f"(ease/worsen/N-A/unchanged)",
            has_label and marker_ok,
            detail="missing `**Python:**` line or a valid marker keyword",
        )


# --- Test 3: README documents the toggle + Python limitations --------------

def test_readme_documents_toggle() -> None:
    text = README.read_text(encoding="utf-8")

    # Decision matrix + both engine values + the userConfig key
    _check(
        "README names the notebook_engine userConfig",
        "notebook_engine" in text,
        detail="`notebook_engine` not found in README",
    )
    _check(
        "README documents both engine values (pyspark + python)",
        "pyspark" in text and "python" in text,
        detail="missing one of the engine values",
    )
    # Decision matrix: a table row contrasting the two engines (kernel row).
    _check(
        "README contains the engine decision matrix",
        bool(re.search(r"`pyspark`.*\|.*`python`", text))
        or ("Kernel" in text and "jupyter" in text and "synapse_pyspark" in text),
        detail="no decision-matrix table contrasting pyspark vs python",
    )

    # Python engine limitations (Slice 7 addition)
    lower = text.lower()
    _check(
        "README documents 'no env vars / Environment item' limitation",
        "environment item" in lower or "env var" in lower,
        detail="missing the no-env-vars/Environment-item limitation",
    )
    _check(
        "README documents the single-node memory limitation",
        "single-node" in lower or "single node" in lower,
        detail="missing the single-node memory limitation",
    )
    _check(
        "README documents 'some Delta features unsupported'",
        "delta" in lower
        and ("unsupported" in lower or "not fully supported" in lower
             or "not supported" in lower),
        detail="missing the Delta-features-unsupported limitation",
    )


def main() -> int:
    test_catalog_parses_with_engine_column()
    test_every_risk_has_engine_note()
    test_readme_documents_toggle()

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
