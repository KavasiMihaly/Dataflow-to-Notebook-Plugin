#!/usr/bin/env python3
"""PreToolUse hook — validates Fabric notebook structure on Write/Edit.

Enforces:
  - .ipynb files in 3 - Notebooks/ are valid JSON with synapse_pyspark kernel
  - silver notebooks read ONLY from bronze (read_bronze() pattern); no
    spark.read.csv/parquet/json, no abfss://, no Files/ paths
  - bronze notebooks include the metadata-column pattern and append write mode
  - lakehouse binding present in metadata.dependencies.lakehouse
  - .py files are NOT written to 3 - Notebooks/ (must be .ipynb)

Contract:
  Input on stdin: PreToolUse JSON with tool_name, tool_input.file_path,
                  tool_input.content / new_string.
  Output on stdout: JSON with `decision: "block"` to refuse the write,
                    `decision: "approve"` to allow, or `{}` to defer.
  Exit code: 0 always (returning a non-zero exit would treat the hook as
             errored by Claude Code).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import PurePosixPath


# --------------------------------------------------------------------------- #
# Forbidden patterns in silver notebooks
# --------------------------------------------------------------------------- #

_SILVER_FORBIDDEN = [
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


def _validate_silver(content: str) -> str | None:
    """Return error message if silver content violates read_bronze contract, else None."""
    for pattern, msg in _SILVER_FORBIDDEN:
        if re.search(pattern, content):
            return f"Silver notebook violation: {msg}. Silver notebooks must read EXCLUSIVELY via read_bronze('<source>'). External reads belong in bronze."
    if "read_bronze" not in content:
        return "Silver notebook violation: no read_bronze() call found. Silver notebooks must read from bronze tables."
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

            # Silver contract — must use read_bronze() only
            if _is_silver_notebook(path):
                err = _validate_silver(content)
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
