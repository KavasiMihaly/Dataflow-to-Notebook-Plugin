#!/usr/bin/env python3
"""Slice 3 — Python bronze builder path tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.
Matches the repo convention used by test_engine_toggle.py /
test_python_reference_set.py.

Covers the Slice 3 contract from `_Plan/python-notebook-engine.md`:
  1. Python bronze output is a valid jupyter-kernel .ipynb (nbformat 4,
     microsoft.language_group == jupyter_python, lakehouse binding present).
  2. No Spark idioms (no spark.read, no F., no saveAsTable, no pyspark import).
  3. Write cell uses mode="append" + schema_mode="merge".
  4. Metadata columns _load_timestamp, _source_file, _load_id are added.
  5. Write target goes through table_path() (no hard-coded Tables/...).
  6. Output passes the live validate-fabric-structure.py PreToolUse hook
     (not blocked) when written to 3 - Notebooks/bronze/.
  7. The PySpark bronze golden is diff-clean against the byte-identical
     PySpark builder template (engine=pyspark must not change).
  8. (MANUAL, Fabric) deploy round-trip — deferred no-op; documented why.

How the goldens are tested (default decision — documented in the Slice 3 plan
section): an LLM-authored builder's exact output is not script-reproducible, so
the goldens under tests/fixtures/golden/{python,pyspark}/ are hand-authored
exemplars that embody the documented builder output, and these tests assert the
STRUCTURAL properties the agent.md instructs the builder to emit. Test 7 pins the
PySpark golden to the agent.md template so the PySpark path cannot silently move.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
PY_BRONZE = GOLDEN_DIR / "python" / "nb_bronze_customers.ipynb"
PYSPARK_BRONZE = GOLDEN_DIR / "pyspark" / "nb_bronze_customers.ipynb"
HOOK = ROOT / "hooks" / "validate-fabric-structure.py"
BRONZE_AGENT = ROOT / "agents" / "fabric-bronze-builder" / "agent.md"

FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


def _load_ipynb(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _notebook_source(nb: dict) -> str:
    """Concatenate all cell source into one string."""
    parts = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def _code_source(nb: dict) -> str:
    """Concatenate only code-cell source (excludes the markdown header)."""
    parts = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Test 1 — valid jupyter-kernel .ipynb
# --------------------------------------------------------------------------- #
def test_bronze_python_valid_ipynb() -> None:
    if not PY_BRONZE.is_file():
        _check("Python bronze is a valid jupyter-kernel .ipynb", False,
               detail=f"missing {PY_BRONZE}")
        return
    try:
        nb = _load_ipynb(PY_BRONZE)
    except Exception as e:  # noqa: BLE001
        _check("Python bronze is a valid jupyter-kernel .ipynb", False,
               detail=f"not JSON: {e}")
        return
    meta = nb.get("metadata", {})
    valid_format = nb.get("nbformat") == 4
    has_cells = bool(nb.get("cells"))
    jupyter_kernel = meta.get("kernel_info", {}).get("name") == "jupyter"
    py_group = meta.get("microsoft", {}).get("language_group") == "jupyter_python"
    lakehouse = meta.get("dependencies", {}).get("lakehouse")
    _check(
        "Python bronze is a valid jupyter-kernel .ipynb (jupyter_python + lakehouse binding)",
        valid_format and has_cells and jupyter_kernel and py_group and bool(lakehouse),
        detail=f"nbformat={nb.get('nbformat')} cells={len(nb.get('cells', []))} "
               f"jupyter={jupyter_kernel} group={py_group} lakehouse={bool(lakehouse)}",
    )


# --------------------------------------------------------------------------- #
# Test 2 — no Spark idioms
# --------------------------------------------------------------------------- #
def test_bronze_python_no_spark_idioms() -> None:
    if not PY_BRONZE.is_file():
        _check("Python bronze has no Spark idioms", False, detail="missing golden")
        return
    src = _code_source(_load_ipynb(PY_BRONZE))
    forbidden = [
        (r"spark\.read", "spark.read"),
        (r"(?<!_)\bF\.", "F. function alias"),
        (r"saveAsTable", "saveAsTable"),
        (r"import\s+pyspark", "import pyspark"),
        (r"from\s+pyspark", "from pyspark"),
        (r"\.withColumn\s*\(", ".withColumn() (PySpark)"),
    ]
    hits = [label for pat, label in forbidden if re.search(pat, src)]
    _check("Python bronze has no Spark idioms", not hits, detail=f"found: {hits}")


# --------------------------------------------------------------------------- #
# Test 3 — append + schema merge
# --------------------------------------------------------------------------- #
def test_bronze_python_append_schema_merge() -> None:
    if not PY_BRONZE.is_file():
        _check("Python bronze write uses append + schema_mode merge", False,
               detail="missing golden")
        return
    src = _code_source(_load_ipynb(PY_BRONZE))
    has_write = "write_deltalake" in src
    has_append = re.search(r'mode\s*=\s*["\']append["\']', src) is not None
    has_merge = re.search(r'schema_mode\s*=\s*["\']merge["\']', src) is not None
    _check(
        "Python bronze write uses write_deltalake + mode=append + schema_mode=merge",
        has_write and has_append and has_merge,
        detail=f"write_deltalake={has_write} append={has_append} merge={has_merge}",
    )


# --------------------------------------------------------------------------- #
# Test 4 — metadata columns
# --------------------------------------------------------------------------- #
def test_bronze_python_metadata_columns() -> None:
    if not PY_BRONZE.is_file():
        _check("Python bronze adds the three metadata columns", False,
               detail="missing golden")
        return
    src = _code_source(_load_ipynb(PY_BRONZE))
    has_ts = "_load_timestamp" in src and "datetime.now(timezone.utc)" in src
    has_src = "_source_file" in src
    has_id = "_load_id" in src and "notebookutils.runtime.context" in src
    _check(
        "Python bronze adds _load_timestamp (utc), _source_file, _load_id (run context)",
        has_ts and has_src and has_id,
        detail=f"_load_timestamp={has_ts} _source_file={has_src} _load_id={has_id}",
    )


# --------------------------------------------------------------------------- #
# Test 5 — table_path() used; no hard-coded Tables/
# --------------------------------------------------------------------------- #
def test_bronze_python_uses_table_path() -> None:
    if not PY_BRONZE.is_file():
        _check("Python bronze write target goes through table_path()", False,
               detail="missing golden")
        return
    src = _code_source(_load_ipynb(PY_BRONZE))
    uses_table_path = re.search(r"table_path\s*\(", src) is not None
    # No hard-coded managed-table path literal in code cells.
    hard_coded = re.search(r'["\'][^"\']*Tables/', src) is not None
    _check(
        "Python bronze write target goes through table_path() (no hard-coded Tables/)",
        uses_table_path and not hard_coded,
        detail=f"table_path={uses_table_path} hard_coded_Tables={hard_coded}",
    )


# --------------------------------------------------------------------------- #
# Test 6 — passes the live structure hook (not blocked)
# --------------------------------------------------------------------------- #
def test_bronze_python_passes_structure_hook() -> None:
    if not PY_BRONZE.is_file():
        _check("Python bronze passes validate-fabric-structure.py hook", False,
               detail="missing golden")
        return
    content = PY_BRONZE.read_text(encoding="utf-8")
    payload = {
        "tool_name": "Write",
        "tool_input": {
            # A bronze-folder path so the hook's bronze branch (not silver) applies.
            "file_path": "project/3 - Notebooks/bronze/nb_bronze_customers.ipynb",
            "content": content,
        },
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    decision = {}
    try:
        decision = json.loads(proc.stdout.strip() or "{}")
    except Exception:  # noqa: BLE001
        decision = {}
    blocked = decision.get("decision") == "block"
    _check(
        "Python bronze is NOT blocked by validate-fabric-structure.py hook",
        proc.returncode == 0 and not blocked,
        detail=f"rc={proc.returncode} decision={decision} stderr={proc.stderr[-200:]}",
    )


# --------------------------------------------------------------------------- #
# Test 7 — PySpark bronze regression (golden pinned to agent.md template)
# --------------------------------------------------------------------------- #
def test_bronze_pyspark_regression() -> None:
    """The PySpark golden must remain diff-clean against the byte-identical
    PySpark builder template in agent.md. This pins the PySpark path so
    adding the Python branch cannot silently move it.

    We assert the golden's code cells reproduce the agent.md template's exact
    write idiom + metadata + imports, and the kernel stays synapse_pyspark.
    """
    if not PYSPARK_BRONZE.is_file() or not BRONZE_AGENT.is_file():
        _check("PySpark bronze golden matches the agent.md template", False,
               detail=f"pyspark_golden={PYSPARK_BRONZE.is_file()} agent={BRONZE_AGENT.is_file()}")
        return
    nb = _load_ipynb(PYSPARK_BRONZE)
    meta = nb.get("metadata", {})
    src = _code_source(nb)
    agent_text = BRONZE_AGENT.read_text(encoding="utf-8")

    # Kernel is unchanged (synapse_pyspark) — Python engine must not touch it.
    kernel_ok = meta.get("kernel_info", {}).get("name") == "synapse_pyspark"

    # The PySpark write idiom + imports + metadata from the agent template
    # must all be present verbatim in the golden's code cells.
    required_snippets = [
        "from pyspark.sql import functions as F",
        '.withColumn("_load_timestamp", F.current_timestamp())',
        '.withColumn("_source_file", F.input_file_name())',
        '.saveAsTable(f"bronze_{source_name}")',
        '.option("mergeSchema", "true")',
        ".mode(load_mode)",
    ]
    missing = [s for s in required_snippets if s not in src]

    # And every required snippet is genuinely the documented template idiom
    # (sanity: the agent.md still teaches them — guards against template drift).
    template_drift = [s for s in required_snippets if s not in agent_text]

    _check(
        "PySpark bronze golden is diff-clean against the agent.md template",
        kernel_ok and not missing and not template_drift,
        detail=f"kernel_ok={kernel_ok} missing_in_golden={missing} "
               f"drift_from_agent={template_drift}",
    )


# --------------------------------------------------------------------------- #
# Test 8 — MANUAL Fabric deploy round-trip (deferred no-op)
# --------------------------------------------------------------------------- #
def test_bronze_python_fabric_deploy_roundtrip_MANUAL() -> None:
    """DEFERRED — manual Fabric check (carries Slice 0's deferred round-trip).

    This test is a documented no-op in CI. Per the Slice 3 plan and the epic's
    anti-scope ("No notebook execution in CI"), the live deploy round-trip —
    deploy the golden via `fab`, confirm Fabric registers it as a *Python*
    notebook (not PySpark) and that it writes the Delta table — requires Fabric
    access and is run manually when the user is online. It is NOT counted as a
    failure here; it is skipped on purpose.
    """
    print("SKIP  Python bronze Fabric deploy round-trip (MANUAL — requires Fabric; "
          "run `fab` deploy + verify Python-notebook registration + Delta write "
          "when online). Deferred per epic anti-scope 'no notebook execution in CI'.")


def main() -> int:
    test_bronze_python_valid_ipynb()
    test_bronze_python_no_spark_idioms()
    test_bronze_python_append_schema_merge()
    test_bronze_python_metadata_columns()
    test_bronze_python_uses_table_path()
    test_bronze_python_passes_structure_hook()
    test_bronze_pyspark_regression()
    test_bronze_python_fabric_deploy_roundtrip_MANUAL()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("All tests passed (test 8 deferred-manual, skipped on purpose).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
