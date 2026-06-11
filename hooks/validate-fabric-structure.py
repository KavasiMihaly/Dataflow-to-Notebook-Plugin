#!/usr/bin/env python3
"""PreToolUse hook — validates Fabric notebook structure on Write/Edit.

Engine-aware (Slice 6). The notebook's metadata selects the contract:
  - PySpark engine  — metadata.kernel_info.name == "synapse_pyspark"
                      (or no Python discriminator present). Validated EXACTLY as
                      before — the synapse_pyspark branch is byte-behaviour
                      identical to pre-Slice-6.
  - Python engine   — metadata.microsoft.language_group == "jupyter_python".
                      Single-node polars / delta-rs notebooks.

Enforces (both engines):
  - .ipynb files in 3 - Notebooks/ are valid Jupyter JSON (nbformat 4,
    non-empty cells, metadata.dependencies.lakehouse present)
  - silver notebooks read ONLY from bronze (read_bronze() pattern); the
    forbidden external-read set is engine-specific:
      * PySpark silver — no spark.read.*, no pd.read_*, no abfss://, no Files/
      * Python  silver — no pl.read_csv/parquet/ndjson/scan_*/read_delta of
        external paths, no os.walk/glob of raw, no abfss://, no Files/, no
        pd.read_* — while STILL requiring a read_bronze() call.
  - cross-engine idiom leakage is blocked in BOTH directions:
      * Spark idiom (spark.* / F.col / pyspark import / saveAsTable) inside a
        jupyter_python notebook → block.
      * delta-rs idiom (write_deltalake / import polars / pl.read_*) inside a
        synapse_pyspark notebook → block.
  - .py files are NOT written to 3 - Notebooks/ (must be .ipynb) — both engines.

Contract:
  Input on stdin: PreToolUse JSON with tool_name, tool_input.file_path,
                  tool_input.content / new_string.
  Output on stdout: JSON with `decision: "block"` to refuse the write,
                    `decision: "approve"` to allow, or `{}` to defer.
  Exit code: 0 always (returning a non-zero exit would treat the hook as
             errored by Claude Code). On any internal error the hook DEFERS —
             it never spuriously blocks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import PurePosixPath


# --------------------------------------------------------------------------- #
# Forbidden external-read patterns in SILVER notebooks (PySpark engine)
# --------------------------------------------------------------------------- #

_SILVER_FORBIDDEN_PYSPARK = [
    (r'spark\.read\.format\s*\(', 'spark.read.format() — silver must use read_bronze()'),
    (r'spark\.read\.csv\s*\(', 'spark.read.csv() — silver must use read_bronze()'),
    (r'spark\.read\.parquet\s*\(', 'spark.read.parquet() — silver must use read_bronze()'),
    (r'spark\.read\.json\s*\(', 'spark.read.json() — silver must use read_bronze()'),
    (r'spark\.read\.jdbc\s*\(', 'spark.read.jdbc() — silver must use read_bronze()'),
    (r'pd\.read_csv\s*\(', 'pandas.read_csv() — silver must use read_bronze()'),
    (r'pd\.read_excel\s*\(', 'pandas.read_excel() — silver must use read_bronze()'),
    (r'\babfss://', 'abfss:// path — silver must use read_bronze()'),
    (r'\bwasbs://', 'wasbs:// path — silver must use read_bronze()'),
    (r'["\']Files/', 'Files/ path literal — silver must use read_bronze()'),
]

# --------------------------------------------------------------------------- #
# Forbidden external-read patterns in SILVER notebooks (Python engine)
#
# The single-node Python silver reads EXCLUSIVELY via read_bronze() (which wraps
# pl.read_delta(table_path(...)) inside the utilities notebook). Any direct
# polars/pandas/mount read in the silver BODY would let it bypass the bronze-only
# contract, so the whole external-read surface is banned — including a bare
# pl.read_delta (it could read an arbitrary delta path, not just bronze).
# --------------------------------------------------------------------------- #

_SILVER_FORBIDDEN_PYTHON = [
    (r'pl\.read_csv\s*\(', 'pl.read_csv() — silver must use read_bronze()'),
    (r'pl\.read_parquet\s*\(', 'pl.read_parquet() — silver must use read_bronze()'),
    (r'pl\.read_ndjson\s*\(', 'pl.read_ndjson() — silver must use read_bronze()'),
    (r'pl\.read_json\s*\(', 'pl.read_json() — silver must use read_bronze()'),
    (r'pl\.read_delta\s*\(', 'pl.read_delta() in the silver body — use read_bronze() (it wraps the delta read)'),
    (r'pl\.scan_csv\s*\(', 'pl.scan_csv() — silver must use read_bronze()'),
    (r'pl\.scan_parquet\s*\(', 'pl.scan_parquet() — silver must use read_bronze()'),
    (r'pl\.scan_ndjson\s*\(', 'pl.scan_ndjson() — silver must use read_bronze()'),
    (r'pl\.scan_delta\s*\(', 'pl.scan_delta() — silver must use read_bronze()'),
    (r'\bDeltaTable\s*\(', 'deltalake.DeltaTable(...) in the silver body — use read_bronze()'),
    (r'pd\.read_csv\s*\(', 'pandas.read_csv() — silver must use read_bronze()'),
    (r'pd\.read_excel\s*\(', 'pandas.read_excel() — silver must use read_bronze()'),
    (r'pd\.read_parquet\s*\(', 'pandas.read_parquet() — silver must use read_bronze()'),
    (r'os\.walk\s*\(', 'os.walk() of raw files — silver must use read_bronze()'),
    (r'glob\.glob\s*\(', 'glob.glob() raw file discovery — silver must use read_bronze()'),
    (r'\babfss://', 'abfss:// path — silver must use read_bronze()'),
    (r'\bwasbs://', 'wasbs:// path — silver must use read_bronze()'),
    (r'["\']Files/', 'Files/ path literal — silver must use read_bronze()'),
]

# --------------------------------------------------------------------------- #
# Cross-engine idiom leakage (both blocked — see module docstring for severity)
# --------------------------------------------------------------------------- #

# Spark idioms must NOT appear in a Python (jupyter_python) notebook — there is
# no Spark session in the single-node runtime, so the notebook would fail.
_SPARK_IN_PYTHON_FORBIDDEN = [
    (r'\bspark\.', 'spark.* — Spark session does not exist in a Python (single-node) notebook'),
    (r'(?<![\w.])F\.', 'F.<fn>() pyspark.sql.functions — not available in a Python notebook'),
    (r'import\s+pyspark', 'import pyspark — not available in a Python notebook'),
    (r'from\s+pyspark', 'from pyspark import — not available in a Python notebook'),
    (r'\.saveAsTable\s*\(', '.saveAsTable() (Spark Delta API) — Python uses write_deltalake()'),
    (r'\.withColumnRenamed\s*\(', '.withColumnRenamed() (Spark) — Python uses polars .rename()'),
]

# delta-rs / polars idioms must NOT appear in a PySpark (synapse_pyspark)
# notebook — that is the Python-engine code-path leaking into the Spark path.
_PYTHON_IN_PYSPARK_FORBIDDEN = [
    (r'\bwrite_deltalake\s*\(', 'write_deltalake() (delta-rs) — PySpark uses df.write...saveAsTable()'),
    (r'import\s+polars', 'import polars — single-node idiom leaking into a PySpark notebook'),
    (r'from\s+polars', 'from polars import — single-node idiom leaking into a PySpark notebook'),
    (r'from\s+deltalake\s+import', 'from deltalake import — delta-rs idiom leaking into a PySpark notebook'),
    (r'\bpl\.read_', 'pl.read_* (polars) — single-node idiom leaking into a PySpark notebook'),
]

# --------------------------------------------------------------------------- #
# Bronze required patterns (warn-level — not blocking, but flagged)
# --------------------------------------------------------------------------- #

_BRONZE_RECOMMENDED = [
    ('add_bronze_metadata|_load_timestamp', 'bronze should add metadata column _load_timestamp'),
    ('mode\\(["\']append["\']\\)|mode = ["\']append["\']', 'bronze should use append write mode'),
]


def _emit_decision(decision: str, reason: str) -> None:
    payload = {"decision": decision, "reason": reason}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _emit_defer() -> None:
    sys.stdout.write("{}\n")


def _is_notebook_path(path: str) -> bool:
    return "3 - Notebooks" in path or "/3 - Notebooks/" in path or "\\3 - Notebooks\\" in path


def _is_silver_notebook(path: str) -> bool:
    name = PurePosixPath(path.replace("\\", "/")).name
    return name.startswith("nb_silver_") or "/silver/" in path.replace("\\", "/")


def _is_bronze_notebook(path: str) -> bool:
    name = PurePosixPath(path.replace("\\", "/")).name
    return name.startswith("nb_bronze_") or "/bronze/" in path.replace("\\", "/")


def _detect_engine(content: str) -> str:
    """Detect the notebook engine from its metadata.

    Returns "python" iff the notebook carries the confirmed Python discriminator
    (metadata.microsoft.language_group == "jupyter_python", or kernel_info.name
    == "jupyter"). Otherwise returns "pyspark" — which keeps the synapse_pyspark
    branch byte-behaviour identical for any notebook without the Python markers.

    Falls back to a cheap substring probe if the content is not parseable JSON
    (e.g. an Edit fragment), so leak/forbidden checks still apply on partial
    edits where the metadata block isn't in the fragment.
    """
    try:
        nb = json.loads(content)
        meta = nb.get("metadata", {}) if isinstance(nb, dict) else {}
        ms = meta.get("microsoft", {})
        if isinstance(ms, dict) and ms.get("language_group") == "jupyter_python":
            return "python"
        kinfo = meta.get("kernel_info", {})
        if isinstance(kinfo, dict) and kinfo.get("name") == "jupyter":
            return "python"
        kspec = meta.get("kernelspec", {})
        if isinstance(kspec, dict) and kspec.get("name") == "jupyter":
            return "python"
        return "pyspark"
    except (json.JSONDecodeError, TypeError):
        # Not full JSON (Edit fragment). Probe for the discriminator literal.
        if '"language_group": "jupyter_python"' in content or "jupyter_python" in content:
            return "python"
        return "pyspark"


def _code_source(content: str) -> str:
    """Return the concatenated CODE-cell source of a notebook.

    Idiom scans (forbidden reads + cross-engine leaks) run against code cells
    ONLY — never the metadata. This matters because Fabric's Python-notebook
    metadata embeds a residual `spark_compute` block (`spark.synapse...`) that
    would otherwise false-positive the `\\bspark\\.` leak pattern.

    Falls back to the full content when the payload is not parseable JSON
    (e.g. an Edit fragment that doesn't include the cells[] array) so the checks
    still apply on partial edits.
    """
    try:
        nb = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        return content
    parts = []
    for cell in nb["cells"]:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def _validate_silver(scan: str, engine: str) -> str | None:
    """Return error message if silver code violates read_bronze contract, else None.

    `scan` is the code-cell source (see _code_source). The forbidden
    external-read set is engine-specific; both engines still require a
    read_bronze() call (the bronze-only contract is preserved, never weakened,
    for the Python engine).
    """
    forbidden = _SILVER_FORBIDDEN_PYTHON if engine == "python" else _SILVER_FORBIDDEN_PYSPARK
    for pattern, msg in forbidden:
        if re.search(pattern, scan):
            return f"Silver notebook violation: {msg}. Silver notebooks must read EXCLUSIVELY via read_bronze('<source>'). External reads belong in bronze."
    if "read_bronze" not in scan:
        return "Silver notebook violation: no read_bronze() call found. Silver notebooks must read from bronze tables."
    return None


def _validate_engine_leak(scan: str, engine: str) -> str | None:
    """Return error if cross-engine idioms leak into the wrong kernel, else None.

    `scan` is the code-cell source (see _code_source). Both directions are a
    hard block: a leaked idiom ships a non-runnable notebook (Spark idiom with
    no Spark session, or delta-rs idiom claiming a Spark kernel). See the module
    docstring for the severity rationale.
    """
    leak_set = _SPARK_IN_PYTHON_FORBIDDEN if engine == "python" else _PYTHON_IN_PYSPARK_FORBIDDEN
    other = "PySpark" if engine == "python" else "Python"
    this = "Python" if engine == "python" else "PySpark"
    for pattern, msg in leak_set:
        if re.search(pattern, scan):
            return (
                f"Cross-engine idiom leak: {msg}. This is a {this}-kernel "
                f"(engine={engine}) notebook but it uses a {other}-engine idiom. "
                f"One engine per notebook — regenerate with the correct idiom set."
            )
    return None


def _validate_run_cell(content: str) -> str | None:
    """Return an error if a `%run` magic does not sit ALONE in its own cell.

    Fabric requires a `%run` magic to be the SOLE content of its code cell — it
    may not share the cell with any other code OR even a comment, or Fabric
    raises `MagicUsageError: %run cannot run with other code or magic commands`.
    The target must also be the bare item name (no `/` path) — a repo-relative
    `%run utilities/nb_utils_config` does not resolve on a flat-workspace deploy
    and raises NameError on the helpers.

    Per-cell check, so it parses the cells[] array; on an unparseable fragment
    (Edit) it returns None (defers) — purity can't be judged from a fragment.
    """
    try:
        nb = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        return None
    for cell in nb["cells"]:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        text = src if isinstance(src, str) else "".join(src)
        lines = text.splitlines()
        run_lines = [ln for ln in lines if ln.strip().startswith("%run")]
        if not run_lines:
            continue
        # The cell holds a %run magic: every OTHER line must be blank.
        other = [ln for ln in lines if ln.strip() and not ln.strip().startswith("%run")]
        if other:
            return (
                "`%run` magic must be the SOLE content of its cell (no comment, "
                "label, or other code in the same cell), or Fabric raises "
                "MagicUsageError: %run cannot run with other code or magic commands. "
                f"Offending cell also contains: {other[0].strip()!r}. "
                "Put any label in a separate markdown cell."
            )
        if len(run_lines) > 1:
            return (
                "A code cell contains more than one `%run` magic; each `%run` must "
                "be alone in its own cell (Fabric MagicUsageError otherwise)."
            )
        target = run_lines[0].strip()[len("%run"):].strip()
        if "/" in target or "\\" in target:
            return (
                f"`%run {target}` uses a path-style target; Fabric resolves `%run` "
                "by bare workspace item name. Use `%run nb_utils_config` (deploys "
                "land notebooks as flat items, so a repo path yields NameError)."
            )
    return None


def _validate_ipynb_shape(content: str, path: str) -> str | None:
    """Return error if .ipynb file is not valid Jupyter JSON, else None."""
    try:
        nb = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Invalid JSON in .ipynb file: {e}"
    if not isinstance(nb, dict):
        return "Notebook root is not a JSON object"
    if nb.get("nbformat") != 4:
        return f"Expected nbformat: 4, got: {nb.get('nbformat')}"
    if not isinstance(nb.get("cells"), list) or not nb["cells"]:
        return "Notebook has empty or missing cells array"
    deps = nb.get("metadata", {}).get("dependencies", {}).get("lakehouse")
    if not deps:
        return "Notebook missing metadata.dependencies.lakehouse — required for Fabric runtime binding"
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _emit_defer()
            return 0

        payload = json.loads(raw)

        if payload.get("tool_name") not in ("Write", "Edit"):
            _emit_defer()
            return 0

        tool_input = payload.get("tool_input", {})
        path = tool_input.get("file_path", "")

        if not _is_notebook_path(path):
            _emit_defer()
            return 0

        # Get content — Write uses 'content', Edit uses 'new_string'
        content = tool_input.get("content") or tool_input.get("new_string") or ""

        # Block .py in 3 - Notebooks/ (must be .ipynb)
        if path.endswith(".py") and "/3 - Notebooks/" in path.replace("\\", "/"):
            _emit_decision(
                "block",
                "Fabric notebooks must be .ipynb (Jupyter JSON), not .py. "
                "Deploying .py via REST API places all code in a single mega-cell. "
                "Generate the notebook as .ipynb with proper cells[] array.",
            )
            return 0

        # Validate .ipynb shape
        if path.endswith(".ipynb") and content:
            err = _validate_ipynb_shape(content, path)
            if err:
                _emit_decision("block", err)
                return 0

            # `%run` cell purity (both engines) — the magic must be the sole
            # content of its cell, with a bare item-name target (#18 + #19).
            err = _validate_run_cell(content)
            if err:
                _emit_decision("block", err)
                return 0

            # Engine-aware checks — the notebook metadata selects the contract.
            engine = _detect_engine(content)
            scan = _code_source(content)

            # Cross-engine idiom leakage — applies to BOTH bronze and silver
            # notebooks (a Spark idiom in a Python notebook, or a delta-rs idiom
            # in a PySpark notebook, is a non-runnable build).
            err = _validate_engine_leak(scan, engine)
            if err:
                _emit_decision("block", err)
                return 0

            # Silver contract — must use read_bronze() only (engine-specific
            # forbidden external-read set).
            if _is_silver_notebook(path):
                err = _validate_silver(scan, engine)
                if err:
                    _emit_decision("block", err)
                    return 0

        _emit_defer()
    except Exception:
        # Never block on hook errors
        _emit_defer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
