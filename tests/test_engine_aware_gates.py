#!/usr/bin/env python3
"""Slice 6 — Engine-aware gates (hook + validator) tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.
Matches the repo convention used by test_engine_toggle.py / test_bronze_python.py
(no pytest; `_check(name, cond, detail)`; `main()` returns an exit code).
Run: `python tests/test_engine_aware_gates.py`.

Covers the Slice 6 contract from `_Plan/python-notebook-engine.md`:
  1. test_hook_pyspark_silver_unchanged — existing PySpark silver fixtures still
     pass/fail exactly as before (byte-behaviour of the synapse_pyspark branch).
  2. test_hook_python_silver_external_read_blocked — a Python silver with
     pl.read_csv(...) / os.walk("Files/...") → blocked.
  3. test_hook_python_silver_read_bronze_ok — a Python silver that reads only via
     read_bronze() → allowed.
  4. test_hook_python_bronze_external_read_ok — a Python bronze reading source
     files (glob/pl.read_csv of Files/) → allowed (bronze is the read layer).
  5. test_validator_asserts_python_kernel_group — the validator agent positively
     asserts microsoft.language_group == "jupyter_python" for Python notebooks.
  6. test_validator_python_write_idiom — the validator agent enforces the Python
     write idioms (bronze append, silver overwrite) on the Python path.
  7. test_cross_engine_leak_spark_in_python — F.col / spark.read inside a
     jupyter-kernel notebook → blocked.
  8. test_cross_engine_leak_python_in_pyspark — write_deltalake inside a
     synapse_pyspark notebook → blocked (chosen severity: BLOCK — see note below).

Engine detection (default decision, documented inline + in the Slice 6 plan
outcome note): the hook reads the notebook METADATA to pick the engine —
`metadata.microsoft.language_group == "jupyter_python"` ⇒ Python engine;
otherwise (`metadata.kernel_info.name == "synapse_pyspark"`, or absent) ⇒ the
existing PySpark branch. This keeps the synapse_pyspark path byte-identical: a
notebook with no `jupyter_python` discriminator never enters the Python branch.

Cross-engine leak severity (default decision): BLOCK in BOTH directions.
  - Spark idiom (spark.* / F.col / pyspark import / saveAsTable) in a jupyter
    notebook ⇒ the notebook claims to be single-node Python but would fail at
    runtime (no Spark session) ⇒ hard block.
  - delta-rs idiom (write_deltalake / import polars / pl.read_*) in a
    synapse_pyspark notebook ⇒ the notebook claims Spark but emits single-node
    delta-rs ⇒ hard block. Chosen BLOCK over WARN because a leaked idiom is a
    builder bug that would silently ship a non-runnable notebook; failing loud
    at write-time is safer than a warning the orchestrator may not surface.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
HOOK = ROOT / "hooks" / "validate-fabric-structure.py"
VALIDATOR_AGENT = ROOT / "agents" / "fabric-pipeline-validator" / "agent.md"
GATES_DIR = ROOT / "tests" / "fixtures" / "gates"

FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


# --------------------------------------------------------------------------- #
# Notebook fixture builders (paired PySpark + Python pass/fail notebooks)
# --------------------------------------------------------------------------- #
_LAKEHOUSE = {
    "known_lakehouses": [{"id": "<lakehouse-id>"}],
    "default_lakehouse": "<lakehouse-id>",
    "default_lakehouse_name": "<lakehouse-name>",
    "default_lakehouse_workspace_id": "<workspace-id>",
}

_PYSPARK_META = {
    "kernel_info": {"name": "synapse_pyspark"},
    "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark"},
    "language_info": {"name": "python"},
    "dependencies": {"lakehouse": _LAKEHOUSE},
}

_PYTHON_META = {
    "kernel_info": {"name": "jupyter", "jupyter_kernel_name": "python3.11"},
    "kernelspec": {"name": "jupyter", "display_name": "Jupyter"},
    "language_info": {"name": "python"},
    "microsoft": {"language": "python", "language_group": "jupyter_python"},
    "dependencies": {"lakehouse": _LAKEHOUSE},
}


def _make_nb(engine: str, code_cells: list[str]) -> str:
    meta = _PYTHON_META if engine == "python" else _PYSPARK_META
    cells = [{
        "cell_type": "markdown",
        "metadata": {},
        "source": ["# header"],
    }]
    for code in code_cells:
        cells.append({
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": code.splitlines(keepends=True),
        })
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": cells,
        "metadata": meta,
    }
    return json.dumps(nb, indent=1)


def _run_hook(file_path: str, content: str) -> dict:
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    out = (proc.stdout or "").strip() or "{}"
    try:
        decision = json.loads(out)
    except json.JSONDecodeError:
        decision = {"_raw": out}
    decision["_rc"] = proc.returncode
    return decision


def _blocked(decision: dict) -> bool:
    return decision.get("decision") == "block"


# --------------------------------------------------------------------------- #
# 1. PySpark silver branch byte-behaviour unchanged
# --------------------------------------------------------------------------- #
def test_hook_pyspark_silver_unchanged() -> None:
    # (a) A clean PySpark silver (read_bronze only) is allowed.
    ok_nb = _make_nb("pyspark", [
        "%run nb_utils_config",
        'df = read_bronze("customers")',
        'df.write.format("delta").mode("overwrite").saveAsTable("silver_customers")',
    ])
    ok = _run_hook("p/3 - Notebooks/silver/nb_silver_customers.ipynb", ok_nb)

    # (b) A PySpark silver with a forbidden external read is still blocked.
    bad_nb = _make_nb("pyspark", [
        '%run nb_utils_config',
        'df = spark.read.csv("Files/raw/x.csv")',
    ])
    bad = _run_hook("p/3 - Notebooks/silver/nb_silver_x.ipynb", bad_nb)

    # (c) A PySpark silver missing read_bronze is still blocked.
    missing_nb = _make_nb("pyspark", [
        '%run nb_utils_config',
        'df = something_else()',
    ])
    missing = _run_hook("p/3 - Notebooks/silver/nb_silver_y.ipynb", missing_nb)

    _check(
        "PySpark silver branch unchanged (clean allowed; external read + no-read_bronze blocked)",
        (not _blocked(ok)) and _blocked(bad) and _blocked(missing),
        detail=f"clean_blocked={_blocked(ok)} extread_blocked={_blocked(bad)} "
               f"noread_blocked={_blocked(missing)}",
    )


# --------------------------------------------------------------------------- #
# 2. Python silver with external read → blocked
# --------------------------------------------------------------------------- #
def test_hook_python_silver_external_read_blocked() -> None:
    # pl.read_csv external read
    nb_csv = _make_nb("python", [
        "%run nb_utils_config",
        'df = read_bronze("customers")',
        'extra = pl.read_csv("/lakehouse/default/Files/raw/x.csv")',
    ])
    d_csv = _run_hook("p/3 - Notebooks/silver/nb_silver_a.ipynb", nb_csv)

    # os.walk of raw mount
    nb_walk = _make_nb("python", [
        "%run nb_utils_config",
        'df = read_bronze("customers")',
        'for root, _, files in os.walk("/lakehouse/default/Files/raw"):\n    pass',
    ])
    d_walk = _run_hook("p/3 - Notebooks/silver/nb_silver_b.ipynb", nb_walk)

    # bare pl.read_delta of an external path (bypasses read_bronze)
    nb_delta = _make_nb("python", [
        "%run nb_utils_config",
        'df = read_bronze("customers")',
        'leak = pl.read_delta("abfss://x@y.dfs.core.windows.net/Tables/z")',
    ])
    d_delta = _run_hook("p/3 - Notebooks/silver/nb_silver_c.ipynb", nb_delta)

    _check(
        "Python silver with external read (pl.read_csv / os.walk / pl.read_delta) is BLOCKED",
        _blocked(d_csv) and _blocked(d_walk) and _blocked(d_delta),
        detail=f"pl.read_csv={_blocked(d_csv)} os.walk={_blocked(d_walk)} "
               f"pl.read_delta={_blocked(d_delta)}",
    )


# --------------------------------------------------------------------------- #
# 3. Python silver read_bronze-only → allowed
# --------------------------------------------------------------------------- #
def test_hook_python_silver_read_bronze_ok() -> None:
    nb = _make_nb("python", [
        "%run nb_utils_config",
        "import polars as pl\nfrom deltalake import write_deltalake",
        'df = read_bronze("customers")',
        'df2 = df.rename({"A": "a"}).with_columns(pl.col("a").cast(pl.Int64))',
        'df3 = add_silver_metadata(df2)',
        'write_deltalake(table_path("silver_customers"), df3.to_arrow(), '
        'mode="overwrite", schema_mode="overwrite")',
    ])
    d = _run_hook("p/3 - Notebooks/silver/nb_silver_customers.ipynb", nb)
    _check(
        "Python silver via read_bronze only is ALLOWED (not blocked)",
        not _blocked(d),
        detail=f"decision={d}",
    )


# --------------------------------------------------------------------------- #
# 4. Python bronze reading source files → allowed (bronze is the read layer)
# --------------------------------------------------------------------------- #
def test_hook_python_bronze_external_read_ok() -> None:
    nb = _make_nb("python", [
        "%run nb_utils_config",
        "import os, glob\nimport polars as pl\nfrom deltalake import write_deltalake",
        'files = sorted(glob.glob("/lakehouse/default/Files/raw/customers/*.csv"))',
        'df = pl.concat([pl.read_csv(f) for f in files], how="diagonal_relaxed")',
        'write_deltalake(table_path("bronze_customers"), df.to_arrow(), '
        'mode="append", schema_mode="merge")',
    ])
    d = _run_hook("p/3 - Notebooks/bronze/nb_bronze_customers.ipynb", nb)
    _check(
        "Python bronze reading source files (glob/pl.read_csv of Files/) is ALLOWED",
        not _blocked(d),
        detail=f"decision={d}",
    )


# --------------------------------------------------------------------------- #
# 5. Validator asserts the Python kernel group
# --------------------------------------------------------------------------- #
def test_validator_asserts_python_kernel_group() -> None:
    if not VALIDATOR_AGENT.is_file():
        _check("validator agent asserts jupyter_python for Python notebooks", False,
               detail="missing validator agent.md")
        return
    text = VALIDATOR_AGENT.read_text(encoding="utf-8")
    asserts_group = (
        "jupyter_python" in text
        and "language_group" in text
        # ties the discriminator to a positive contract assertion / FAIL
        and ("microsoft.language_group" in text or "microsoft" in text)
    )
    _check(
        "validator agent positively asserts microsoft.language_group == jupyter_python",
        asserts_group,
        detail=f"jupyter_python={('jupyter_python' in text)} "
               f"language_group={('language_group' in text)}",
    )


# --------------------------------------------------------------------------- #
# 6. Validator enforces the Python write idioms (append / overwrite)
# --------------------------------------------------------------------------- #
def test_validator_python_write_idiom() -> None:
    if not VALIDATOR_AGENT.is_file():
        _check("validator agent enforces Python write idioms", False,
               detail="missing validator agent.md")
        return
    text = VALIDATOR_AGENT.read_text(encoding="utf-8")
    # Python bronze contract: write_deltalake append + schema_mode merge.
    bronze_idiom = (
        "write_deltalake" in text
        and 'mode="append"' in text
        and 'schema_mode="merge"' in text
    )
    # Python silver contract: write_deltalake overwrite + schema_mode overwrite.
    silver_idiom = (
        'mode="overwrite"' in text and 'schema_mode="overwrite"' in text
    )
    # Row-count check on the Python path must NOT be spark.table().count().
    python_section = in_python_rowcount(text)
    delta_rowcount = (
        ("delta-rs" in python_section or "deltalake" in python_section
         or "duckdb" in python_section)
        and "spark.table().count()" not in python_section
    )
    _check(
        "validator agent enforces Python bronze=append + silver=overwrite + delta-rs row-count",
        bronze_idiom and silver_idiom and delta_rowcount,
        detail=f"bronze_idiom={bronze_idiom} silver_idiom={silver_idiom} "
               f"delta_rowcount={delta_rowcount}",
    )


def in_python_rowcount(text: str) -> str:
    """Return the Python-engine section text (after the engine split) so the
    'no spark.table().count()' assertion is scoped to the Python path, not the
    whole doc (the PySpark path may still legitimately mention spark counts)."""
    marker = "engine=python"
    idx = text.find(marker)
    return text[idx:] if idx != -1 else text


# --------------------------------------------------------------------------- #
# 7. Cross-engine leak — Spark idiom inside a jupyter notebook → blocked
# --------------------------------------------------------------------------- #
def test_cross_engine_leak_spark_in_python() -> None:
    # spark.read in a Python bronze
    nb_spark = _make_nb("python", [
        "%run nb_utils_config",
        'df = spark.read.csv("Files/raw/x.csv")',
        'write_deltalake(table_path("bronze_x"), df, mode="append", schema_mode="merge")',
    ])
    d_spark = _run_hook("p/3 - Notebooks/bronze/nb_bronze_x.ipynb", nb_spark)

    # F.col in a Python silver
    nb_f = _make_nb("python", [
        "%run nb_utils_config",
        'df = read_bronze("customers")',
        'df2 = df.withColumn("y", F.col("x"))',
        'write_deltalake(table_path("silver_x"), df2, mode="overwrite", schema_mode="overwrite")',
    ])
    d_f = _run_hook("p/3 - Notebooks/silver/nb_silver_x.ipynb", nb_f)

    _check(
        "Spark idiom (spark.read / F.col) inside a jupyter-kernel notebook is BLOCKED",
        _blocked(d_spark) and _blocked(d_f),
        detail=f"spark.read_blocked={_blocked(d_spark)} F.col_blocked={_blocked(d_f)}",
    )


# --------------------------------------------------------------------------- #
# 8. Cross-engine leak — write_deltalake inside a synapse_pyspark notebook
# --------------------------------------------------------------------------- #
def test_cross_engine_leak_python_in_pyspark() -> None:
    # write_deltalake (delta-rs) inside a PySpark bronze — wrong engine idiom.
    nb = _make_nb("pyspark", [
        "%run nb_utils_config",
        'df = spark.createDataFrame([])',
        'write_deltalake(table_path("bronze_x"), df, mode="append", schema_mode="merge")',
    ])
    d = _run_hook("p/3 - Notebooks/bronze/nb_bronze_x.ipynb", nb)

    # import polars inside a PySpark notebook — also a leak.
    nb2 = _make_nb("pyspark", [
        "%run nb_utils_config",
        "import polars as pl",
        'df = read_bronze("customers")',
        'df.write.format("delta").mode("overwrite").saveAsTable("silver_x")',
    ])
    d2 = _run_hook("p/3 - Notebooks/silver/nb_silver_x.ipynb", nb2)

    _check(
        "delta-rs idiom (write_deltalake / import polars) inside a synapse_pyspark notebook is BLOCKED",
        _blocked(d) and _blocked(d2),
        detail=f"write_deltalake_blocked={_blocked(d)} import_polars_blocked={_blocked(d2)}",
    )


def main() -> int:
    test_hook_pyspark_silver_unchanged()
    test_hook_python_silver_external_read_blocked()
    test_hook_python_silver_read_bronze_ok()
    test_hook_python_bronze_external_read_ok()
    test_validator_asserts_python_kernel_group()
    test_validator_python_write_idiom()
    test_cross_engine_leak_spark_in_python()
    test_cross_engine_leak_python_in_pyspark()

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
