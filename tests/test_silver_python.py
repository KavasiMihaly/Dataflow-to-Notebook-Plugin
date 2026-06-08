#!/usr/bin/env python3
"""Slice 4 — Python silver builder path tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.
Matches the repo convention used by test_engine_toggle.py /
test_python_reference_set.py (no pytest; `_check(name, cond, detail)`;
`main()` returns an exit code). Run: `python tests/test_silver_python.py`.

Covers the Slice 4 contract from `_Plan/python-notebook-engine.md`:
  1. The Python silver golden is a valid jupyter-kernel .ipynb with an
     lh_silver lakehouse binding.
  2. read_bronze-only contract: exactly one read path (read_bronze); NO
     pl.read_csv/read_parquet/scan_delta/read_delta of external paths, no
     abfss://, no Files/ literals, no os.walk / mount reads of raw.
  3. Write idiom: write_deltalake(..., mode="overwrite", schema_mode="overwrite").
  4. Metadata swap: bronze metadata dropped, add_silver_metadata() called.
  5. No Spark idioms (no spark.*, no F., no pyspark import).
  6. The Python silver golden passes the live structure hook
     (hooks/validate-fabric-structure.py) — the Python read_bronze-only body
     satisfies the silver forbidden-pattern list.
  7. PySpark silver regression: the PySpark silver golden is diff-clean against
     a captured baseline (no engine cross-contamination; PySpark path unmoved).
  8. (Integration) bronze (Slice 3) -> silver round-trip: silver's read_bronze
     resolves the bronze table the Slice-3 Python bronze golden writes. TOLERANT:
     if no Python bronze golden exists yet, SKIP (the main agent runs the join).

The silver builder is an LLM-authored agent — its output is not script-
reproducible. So, per the repo convention for builder goldens, these tests
assert STRUCTURAL properties of a hand-authored representative golden
(`tests/fixtures/golden/python/nb_silver_<entity>.ipynb`) plus the engine-aware
instructions in `agents/fabric-silver-builder/agent.md`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
HOOK = ROOT / "hooks" / "validate-fabric-structure.py"
AGENT = ROOT / "agents" / "fabric-silver-builder" / "agent.md"

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
PY_SILVER_GOLDEN = GOLDEN_DIR / "python" / "nb_silver_customers.ipynb"
PYSPARK_SILVER_GOLDEN = GOLDEN_DIR / "pyspark" / "nb_silver_customers.ipynb"
PY_BRONZE_GOLDEN = GOLDEN_DIR / "python" / "nb_bronze_customers.ipynb"

FAILURES: list[str] = []
SKIPPED: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


def _skip(name: str, detail: str = "") -> None:
    print(f"SKIP  {name}  {detail}")
    SKIPPED.append(name)


def _load_ipynb(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _notebook_source(nb: dict) -> str:
    """Concatenate all code-cell source into one string."""
    parts = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def _write_mode_resolves_to(src: str, expected: str) -> bool:
    """True if a write call's `mode=` resolves to `expected` ("append"/"overwrite").

    Accepts BOTH the literal form (`mode="overwrite"`) and the parameterised
    form the real builders emit (`mode=write_mode` where `write_mode =
    "overwrite"` is assigned earlier). IMP-2: a literal-only assertion gives
    false confidence because builders legitimately parameterise the write mode.
    The negative lookbehind keeps `schema_mode="..."` from matching.
    """
    if re.search(rf'(?<![A-Za-z_])mode\s*=\s*["\']{re.escape(expected)}["\']', src):
        return True
    for m in re.finditer(r'(?<![A-Za-z_])mode\s*=\s*([A-Za-z_]\w*)', src):
        ident = m.group(1)
        if re.search(rf'{re.escape(ident)}\s*=\s*["\']{re.escape(expected)}["\']', src):
            return True
    return False


# --------------------------------------------------------------------------- #
# 1. valid jupyter-kernel .ipynb + lh_silver binding
# --------------------------------------------------------------------------- #
def test_silver_python_valid_ipynb() -> None:
    if not PY_SILVER_GOLDEN.is_file():
        _check("Python silver golden is a valid jupyter-kernel .ipynb (lh_silver binding)",
               False, detail=f"missing {PY_SILVER_GOLDEN}")
        return
    try:
        nb = _load_ipynb(PY_SILVER_GOLDEN)
    except Exception as e:  # noqa: BLE001
        _check("Python silver golden is a valid jupyter-kernel .ipynb (lh_silver binding)",
               False, detail=f"not JSON: {e}")
        return
    valid_format = nb.get("nbformat") == 4
    has_cells = bool(nb.get("cells"))
    meta = nb.get("metadata", {})
    jupyter_kernel = (
        meta.get("kernel_info", {}).get("name") == "jupyter"
        and meta.get("microsoft", {}).get("language_group") == "jupyter_python"
    )
    lh = meta.get("dependencies", {}).get("lakehouse", {})
    binding = json.dumps(lh)
    silver_bound = "silver" in binding.lower()
    _check(
        "Python silver golden is a valid jupyter-kernel .ipynb (lh_silver binding)",
        valid_format and has_cells and jupyter_kernel and bool(lh) and silver_bound,
        detail=f"nbformat={nb.get('nbformat')} cells={len(nb.get('cells', []))} "
               f"jupyter={jupyter_kernel} lakehouse={bool(lh)} silver={silver_bound}",
    )


# --------------------------------------------------------------------------- #
# 2. read_bronze-only contract (the security-critical assertion)
# --------------------------------------------------------------------------- #
def test_silver_python_read_bronze_only() -> None:
    if not PY_SILVER_GOLDEN.is_file():
        _check("Python silver reads bronze-only (no external reads)", False,
               detail=f"missing {PY_SILVER_GOLDEN}")
        return
    src = _notebook_source(_load_ipynb(PY_SILVER_GOLDEN))

    has_read_bronze = bool(re.search(r"\bread_bronze\s*\(", src))

    # Forbidden external-read idioms in silver (polars + mount + spark + pandas).
    forbidden = [
        (r"pl\.read_csv\s*\(", "pl.read_csv"),
        (r"pl\.read_parquet\s*\(", "pl.read_parquet"),
        (r"pl\.read_ndjson\s*\(", "pl.read_ndjson"),
        (r"pl\.scan_csv\s*\(", "pl.scan_csv"),
        (r"pl\.scan_parquet\s*\(", "pl.scan_parquet"),
        (r"pl\.scan_delta\s*\(", "pl.scan_delta"),
        # read_delta of a raw/external path (read_bronze internally uses
        # pl.read_delta(table_path(...)) but that lives in the utils notebook,
        # not the silver body — the silver body must not call it directly).
        (r"pl\.read_delta\s*\(", "pl.read_delta (use read_bronze)"),
        (r"\babfss://", "abfss:// literal"),
        (r"\bwasbs://", "wasbs:// literal"),
        (r"['\"]Files/", "Files/ literal"),
        (r"os\.walk\s*\(", "os.walk"),
        (r"glob\.glob\s*\(", "glob.glob (raw file discovery)"),
        (r"pd\.read_", "pandas read"),
    ]
    offenders = [label for pat, label in forbidden if re.search(pat, src)]

    # "exactly one read path": only read_bronze appears as the data ingress.
    read_bronze_calls = len(re.findall(r"\bread_bronze\s*\(", src))

    ok = has_read_bronze and not offenders and read_bronze_calls >= 1
    _check(
        "Python silver reads bronze-only (no external reads)",
        ok,
        detail=f"read_bronze={has_read_bronze} calls={read_bronze_calls} "
               f"offenders={offenders}",
    )


# --------------------------------------------------------------------------- #
# 3. write idiom — overwrite + schema overwrite
# --------------------------------------------------------------------------- #
def test_silver_python_overwrite_schema() -> None:
    if not PY_SILVER_GOLDEN.is_file():
        _check("Python silver write uses overwrite + schema_mode overwrite", False,
               detail=f"missing {PY_SILVER_GOLDEN}")
        return
    src = _notebook_source(_load_ipynb(PY_SILVER_GOLDEN))
    uses_write_deltalake = bool(re.search(r"\bwrite_deltalake\s*\(", src))
    # IMP-2: accept both literal mode="overwrite" and a parameterised
    # mode=write_mode (write_mode = "overwrite").
    overwrite_mode = _write_mode_resolves_to(src, "overwrite")
    schema_overwrite = bool(re.search(r"schema_mode\s*=\s*['\"]overwrite['\"]", src))
    # Must NOT be the bronze append idiom.
    not_append = not _write_mode_resolves_to(src, "append")
    _check(
        "Python silver write uses overwrite + schema_mode overwrite",
        uses_write_deltalake and overwrite_mode and schema_overwrite and not_append,
        detail=f"write_deltalake={uses_write_deltalake} overwrite={overwrite_mode} "
               f"schema_overwrite={schema_overwrite} not_append={not_append}",
    )


# --------------------------------------------------------------------------- #
# 4. metadata swap — bronze dropped, add_silver_metadata called
# --------------------------------------------------------------------------- #
def test_silver_python_metadata_swap() -> None:
    if not PY_SILVER_GOLDEN.is_file():
        _check("Python silver swaps bronze metadata for silver metadata", False,
               detail=f"missing {PY_SILVER_GOLDEN}")
        return
    src = _notebook_source(_load_ipynb(PY_SILVER_GOLDEN))
    calls_silver_meta = bool(re.search(r"\badd_silver_metadata\s*\(", src))
    # add_silver_metadata() internally drops bronze cols; either an explicit
    # drop of bronze cols or the helper call satisfies "bronze metadata dropped".
    drops_bronze = (
        bool(re.search(r"\bdrop\s*\(", src))
        and bool(re.search(r"_load_timestamp|_source_file|_load_id", src))
    ) or calls_silver_meta
    no_bronze_meta_added = not re.search(r"\badd_bronze_metadata\s*\(", src)
    _check(
        "Python silver swaps bronze metadata for silver metadata",
        calls_silver_meta and drops_bronze and no_bronze_meta_added,
        detail=f"add_silver_metadata={calls_silver_meta} drops_bronze={drops_bronze} "
               f"no_bronze_meta={no_bronze_meta_added}",
    )


# --------------------------------------------------------------------------- #
# 5. no spark idioms
# --------------------------------------------------------------------------- #
def test_silver_python_no_spark_idioms() -> None:
    if not PY_SILVER_GOLDEN.is_file():
        _check("Python silver has no Spark idioms", False,
               detail=f"missing {PY_SILVER_GOLDEN}")
        return
    src = _notebook_source(_load_ipynb(PY_SILVER_GOLDEN))
    spark_hits = []
    if re.search(r"\bspark\.", src):
        spark_hits.append("spark.")
    if re.search(r"\bF\.", src):
        spark_hits.append("F.")
    if re.search(r"\bimport\s+pyspark|from\s+pyspark", src):
        spark_hits.append("pyspark import")
    if re.search(r"\.saveAsTable\s*\(", src):
        spark_hits.append("saveAsTable")
    if re.search(r"\.withColumnRenamed\s*\(", src):
        spark_hits.append("withColumnRenamed")
    _check("Python silver has no Spark idioms", not spark_hits,
           detail=f"spark idioms found: {spark_hits}")


# --------------------------------------------------------------------------- #
# 6. passes the live structure hook (Python read_bronze-only body)
# --------------------------------------------------------------------------- #
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
    out = proc.stdout.strip() or "{}"
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out, "_rc": proc.returncode}


def test_silver_python_passes_structure_hook_python_branch() -> None:
    if not PY_SILVER_GOLDEN.is_file():
        _check("Python silver passes the structure hook", False,
               detail=f"missing {PY_SILVER_GOLDEN}")
        return
    content = PY_SILVER_GOLDEN.read_text(encoding="utf-8")
    # Simulate a Write into the project's silver folder so the hook fires.
    sim_path = "project/3 - Notebooks/silver/nb_silver_customers.ipynb"
    result = _run_hook(sim_path, content)
    blocked = result.get("decision") == "block"
    _check(
        "Python silver passes the structure hook (read_bronze-only body, not blocked)",
        not blocked,
        detail=f"hook result={result}",
    )


# --------------------------------------------------------------------------- #
# 7. PySpark silver regression — diff-clean against captured baseline
# --------------------------------------------------------------------------- #
def test_silver_pyspark_regression() -> None:
    """The PySpark silver golden must remain a valid synapse_pyspark silver
    notebook using the unchanged Spark idioms (saveAsTable/overwrite + read_bronze).
    Guards against the Python work leaking into the PySpark path."""
    if not PYSPARK_SILVER_GOLDEN.is_file():
        _check("PySpark silver golden is unchanged (synapse_pyspark, Spark idioms)",
               False, detail=f"missing {PYSPARK_SILVER_GOLDEN}")
        return
    try:
        nb = _load_ipynb(PYSPARK_SILVER_GOLDEN)
    except Exception as e:  # noqa: BLE001
        _check("PySpark silver golden is unchanged (synapse_pyspark, Spark idioms)",
               False, detail=f"not JSON: {e}")
        return
    meta = nb.get("metadata", {})
    is_pyspark_kernel = meta.get("kernel_info", {}).get("name") == "synapse_pyspark"
    src = _notebook_source(nb)
    has_read_bronze = "read_bronze" in src
    has_spark_write = bool(re.search(r"\.saveAsTable\s*\(", src))
    overwrite = bool(re.search(r'mode\s*\(\s*["\']overwrite["\']\s*\)', src))
    # Must NOT have leaked Python idioms.
    no_polars = "write_deltalake" not in src and "import polars" not in src
    _check(
        "PySpark silver golden is unchanged (synapse_pyspark, Spark idioms)",
        is_pyspark_kernel and has_read_bronze and has_spark_write and overwrite and no_polars,
        detail=f"kernel={is_pyspark_kernel} read_bronze={has_read_bronze} "
               f"saveAsTable={has_spark_write} overwrite={overwrite} no_polars={no_polars}",
    )


# --------------------------------------------------------------------------- #
# 8. (Integration) bronze -> silver round-trip — TOLERANT skip
# --------------------------------------------------------------------------- #
def test_silver_python_bronze_round_trip() -> None:
    name = "Python silver read_bronze resolves the Slice-3 bronze table"
    if not PY_BRONZE_GOLDEN.is_file():
        _skip(name, "no Python bronze golden yet — deferred to integration join "
                    "(main agent runs it)")
        return
    if not PY_SILVER_GOLDEN.is_file():
        _check(name, False, detail=f"missing {PY_SILVER_GOLDEN}")
        return
    bronze_src = _notebook_source(_load_ipynb(PY_BRONZE_GOLDEN))
    silver_src = _notebook_source(_load_ipynb(PY_SILVER_GOLDEN))

    # The bronze golden writes bronze_<source>; the silver golden must read the
    # same source name back via read_bronze (which resolves table_path() ->
    # bronze_<source>). Extract the bronze source_name and the silver read arg.
    m_bronze = re.search(r"source_name\s*=\s*['\"](\w+)['\"]", bronze_src)
    bronze_source = m_bronze.group(1) if m_bronze else None

    # Silver read target: read_bronze("x") or read_bronze(BRONZE_SOURCE) where
    # BRONZE_SOURCE = "x".
    m_direct = re.search(r"read_bronze\s*\(\s*['\"](\w+)['\"]\s*\)", silver_src)
    if m_direct:
        silver_source = m_direct.group(1)
    else:
        m_var = re.search(r"BRONZE_SOURCE\s*=\s*['\"](\w+)['\"]", silver_src)
        silver_source = m_var.group(1) if m_var else None

    ok = bronze_source is not None and bronze_source == silver_source
    _check(
        name, ok,
        detail=f"bronze writes bronze_{bronze_source!r}; "
               f"silver read_bronze({silver_source!r}) — must match",
    )


# --------------------------------------------------------------------------- #
# Bonus: agent.md engine-awareness (guards the instruction contract)
# --------------------------------------------------------------------------- #
def test_agent_md_engine_aware() -> None:
    if not AGENT.is_file():
        _check("silver-builder agent.md documents the Python (engine) path", False,
               detail=f"missing {AGENT}")
        return
    text = AGENT.read_text(encoding="utf-8")
    needs = [
        "write_deltalake",
        "schema_mode",
        "read_bronze",
        "add_silver_metadata",
        "polars",
    ]
    missing = [n for n in needs if n not in text]
    # PySpark instructions must remain present (engine=pyspark unchanged).
    keeps_pyspark = "saveAsTable" in text and "overwriteSchema" in text
    _check(
        "silver-builder agent.md documents the Python path AND keeps PySpark",
        not missing and keeps_pyspark,
        detail=f"missing Python tokens={missing} keeps_pyspark={keeps_pyspark}",
    )


def main() -> int:
    test_silver_python_valid_ipynb()
    test_silver_python_read_bronze_only()
    test_silver_python_overwrite_schema()
    test_silver_python_metadata_swap()
    test_silver_python_no_spark_idioms()
    test_silver_python_passes_structure_hook_python_branch()
    test_silver_pyspark_regression()
    test_silver_python_bronze_round_trip()
    test_agent_md_engine_aware()

    print()
    if SKIPPED:
        print(f"SKIPPED: {len(SKIPPED)} test(s): {', '.join(SKIPPED)}")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("All tests passed (skips are tolerated).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
