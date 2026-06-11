#!/usr/bin/env python3
"""Slice 2 — Python reference set + utilities notebook tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.
Matches the repo convention used by test_engine_toggle.py / test_risk_catalog.py.

Covers the Slice 2 contract from `_Plan/python-notebook-engine.md`:
  1. python-notebook-metadata.md carries the confirmed jupyter kernel +
     jupyter_python language_group.
  2. The Python nb_utils_config template is a valid jupyter-kernel .ipynb.
  3. The utils template defines all six required helpers.
  4. table_path() resolves schema-enabled -> Tables/dbo/<n>, classic -> Tables/<n>.
  5. The style guide documents the mount-not-fs.ls rule (research 3.3).
  6. --engine python scaffolds the Python utils notebook (not PySpark).
  7. --engine pyspark still scaffolds the PySpark utils (regression).
  8. None of the new files contain local absolute paths (global rule).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
INITIALIZER = ROOT / "skills" / "fabric-project-initializer" / "scripts" / "initialize_fabric_project.py"
TEMPLATES_DIR = ROOT / "skills" / "fabric-project-initializer" / "templates"
PY_UTILS_TEMPLATE = TEMPLATES_DIR / "nb_utils_config_python.ipynb"

REF_DIR = ROOT / "reference"
META_REF = REF_DIR / "python-notebook-metadata.md"
STYLE_REF = REF_DIR / "python-style-guide.md"
DELTA_REF = REF_DIR / "python-delta-patterns.md"

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
PY_BRONZE_GOLDEN = GOLDEN_DIR / "python" / "nb_bronze_customers.ipynb"
PY_SILVER_GOLDEN = GOLDEN_DIR / "python" / "nb_silver_customers.ipynb"

# The single canonical Python-notebook metadata shell (python-notebook-metadata.md
# §"The discriminator"). Both builders MUST emit exactly this (IMP-4).
CANONICAL_SHELL = {
    "kernel_info.name": "jupyter",
    "kernelspec.name": "jupyter",
    "kernelspec.display_name": "Jupyter",
    "microsoft.language_group": "jupyter_python",
}

REQUIRED_HELPERS = [
    "read_bronze",
    "add_bronze_metadata",
    "add_silver_metadata",
    "silver_table",
    "table_path",
    "validate_row_count",
]

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
    """Concatenate all code-cell source into one string."""
    parts = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def _run_initializer(target: Path, engine: str | None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(INITIALIZER),
        "--target", str(target),
        "--name", "Sales Analytics",
        "--workspace", "Development",
        "--description", "Test fixture project",
        "--force",
    ]
    if engine is not None:
        cmd += ["--engine", engine]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))


def test_python_metadata_reference_matches_confirmed() -> None:
    ok = META_REF.is_file()
    text = META_REF.read_text(encoding="utf-8") if ok else ""
    has_kernel = '"name": "jupyter"' in text
    has_group = '"language_group": "jupyter_python"' in text
    _check(
        "python-notebook-metadata.md carries confirmed jupyter + jupyter_python",
        ok and has_kernel and has_group,
        detail=f"exists={ok} kernel={has_kernel} group={has_group}",
    )


def _metadata_shell(nb: dict) -> dict:
    meta = nb.get("metadata", {})
    return {
        "kernel_info.name": meta.get("kernel_info", {}).get("name"),
        "kernelspec.name": meta.get("kernelspec", {}).get("name"),
        "kernelspec.display_name": meta.get("kernelspec", {}).get("display_name"),
        "microsoft.language_group": meta.get("microsoft", {}).get("language_group"),
    }


def test_python_builders_agree_on_metadata_shell() -> None:
    """IMP-4: bronze and silver Python notebooks must carry an IDENTICAL kernel
    metadata shell (kernel_info.name, kernelspec.name/display_name,
    microsoft.language_group), and it must equal the canonical block in
    python-notebook-metadata.md. The integration pass found the real builders
    diverging (bronze kernelspec.name="jupyter" vs silver "python3"); this pins
    both goldens to one shell so a future drift fails here."""
    if not PY_BRONZE_GOLDEN.is_file() or not PY_SILVER_GOLDEN.is_file():
        _check("Python bronze & silver share the canonical metadata shell", False,
               detail=f"bronze={PY_BRONZE_GOLDEN.is_file()} silver={PY_SILVER_GOLDEN.is_file()}")
        return
    bronze_shell = _metadata_shell(_load_ipynb(PY_BRONZE_GOLDEN))
    silver_shell = _metadata_shell(_load_ipynb(PY_SILVER_GOLDEN))
    utils_shell = _metadata_shell(_load_ipynb(PY_UTILS_TEMPLATE)) if PY_UTILS_TEMPLATE.is_file() else {}

    identical = bronze_shell == silver_shell
    matches_canonical = bronze_shell == CANONICAL_SHELL
    utils_ok = (not utils_shell) or (
        utils_shell["kernel_info.name"] == "jupyter"
        and utils_shell["microsoft.language_group"] == "jupyter_python"
    )
    _check(
        "Python bronze & silver share the canonical metadata shell",
        identical and matches_canonical and utils_ok,
        detail=f"bronze={bronze_shell} silver={silver_shell} "
               f"canonical={CANONICAL_SHELL} utils={utils_shell}",
    )


def test_utils_notebook_valid_ipynb() -> None:
    if not PY_UTILS_TEMPLATE.is_file():
        _check("Python nb_utils_config template is a valid jupyter-kernel .ipynb",
               False, detail=f"missing {PY_UTILS_TEMPLATE}")
        return
    try:
        nb = _load_ipynb(PY_UTILS_TEMPLATE)
    except Exception as e:  # noqa: BLE001
        _check("Python nb_utils_config template is a valid jupyter-kernel .ipynb",
               False, detail=f"not JSON: {e}")
        return
    valid_format = nb.get("nbformat") == 4
    has_cells = bool(nb.get("cells"))
    meta = nb.get("metadata", {})
    jupyter_kernel = (
        meta.get("kernel_info", {}).get("name") == "jupyter"
        and meta.get("microsoft", {}).get("language_group") == "jupyter_python"
    )
    _check(
        "Python nb_utils_config template is a valid jupyter-kernel .ipynb",
        valid_format and has_cells and jupyter_kernel,
        detail=f"nbformat={nb.get('nbformat')} cells={len(nb.get('cells', []))} "
               f"jupyter_kernel={jupyter_kernel}",
    )


def test_utils_defines_required_helpers() -> None:
    if not PY_UTILS_TEMPLATE.is_file():
        _check("Python utils defines all six required helpers", False,
               detail=f"missing {PY_UTILS_TEMPLATE}")
        return
    src = _notebook_source(_load_ipynb(PY_UTILS_TEMPLATE))
    missing = [h for h in REQUIRED_HELPERS if not re.search(rf"def\s+{h}\s*\(", src)]
    _check("Python utils defines all six required helpers",
           not missing, detail=f"missing defs: {missing}")


def test_utils_defines_delta_write_kwargs_shim() -> None:
    """The utilities template must define the version-aware delta-rs write shim
    (DELTA_WRITE_KWARGS / _delta_write_kwargs) that owns the schema_mode/engine
    gotcha. Executing the shim must yield engine="rust" for delta-rs < 0.18 and
    {} for >= 0.18. Regression for the 2026-06-11 pyarrow-engine ValueError."""
    if not PY_UTILS_TEMPLATE.is_file():
        _check("Python utils defines the DELTA_WRITE_KWARGS rust-writer shim", False,
               detail=f"missing {PY_UTILS_TEMPLATE}")
        return
    src = _notebook_source(_load_ipynb(PY_UTILS_TEMPLATE))
    defines_constant = "DELTA_WRITE_KWARGS" in src
    m = re.search(r"(def\s+_delta_write_kwargs\s*\(.*?)(?=\nDELTA_WRITE_KWARGS|\ndef\s|\Z)",
                  src, re.DOTALL)
    if not (defines_constant and m):
        _check("Python utils defines the DELTA_WRITE_KWARGS rust-writer shim", False,
               detail=f"constant={defines_constant} shim_def={bool(m)}")
        return

    # Exec the shim with a stubbed deltalake module to assert both version branches.
    def _run(version: str) -> dict:
        ns: dict = {"deltalake": type("M", (), {"__version__": version})()}
        exec(m.group(1), ns)  # noqa: S102 - controlled template source under test
        return ns["_delta_write_kwargs"]()

    try:
        old = _run("0.17.4")     # pyarrow-default era → must inject engine="rust"
        new = _run("0.18.2")     # rust-only era → must pass nothing
        newer = _run("1.0.0")    # engine kwarg removed → must pass nothing
    except Exception as e:  # noqa: BLE001
        _check("Python utils defines the DELTA_WRITE_KWARGS rust-writer shim", False,
               detail=f"exec error: {e}")
        return
    ok = old == {"engine": "rust"} and new == {} and newer == {}
    _check("Python utils defines the DELTA_WRITE_KWARGS rust-writer shim", ok,
           detail=f"0.17={old} 0.18={new} 1.0={newer}")


def test_add_bronze_metadata_avoids_null_dtype() -> None:
    """#20 — the utilities add_bronze_metadata helper must type its string lits
    with dtype=pl.Utf8 and coerce the run id with `or "manual"`, so a None value
    yields a String column (not a polars Null dtype, which delta-rs rejects on
    write with SchemaMismatchError: Invalid data type for Delta Lake: Null)."""
    if not PY_UTILS_TEMPLATE.is_file():
        _check("add_bronze_metadata types its lits Utf8 + coerces run id", False,
               detail=f"missing {PY_UTILS_TEMPLATE}")
        return
    src = _notebook_source(_load_ipynb(PY_UTILS_TEMPLATE))
    m = re.search(r"def\s+add_bronze_metadata\s*\(.*?(?=\ndef\s|\Z)", src, re.DOTALL)
    body = m.group(0) if m else ""
    source_file_typed = re.search(
        r'pl\.lit\([^)]*dtype\s*=\s*pl\.Utf8[^)]*\)\.alias\(\s*["\']_source_file["\']\)', body
    ) is not None
    load_id_typed = re.search(
        r'pl\.lit\(\s*load_id\s*,\s*dtype\s*=\s*pl\.Utf8\s*\)\.alias\(\s*["\']_load_id["\']\)', body
    ) is not None
    run_id_coerced = re.search(r'currentRunId["\']\s*\)\s*or\s*["\']manual["\']', body) is not None
    no_get_default = re.search(r'get\(\s*["\']currentRunId["\']\s*,\s*["\']manual["\']\s*\)', body) is None
    _check(
        "add_bronze_metadata types its lits Utf8 + coerces run id (no Null dtype)",
        bool(m) and source_file_typed and load_id_typed and run_id_coerced and no_get_default,
        detail=f"found={bool(m)} source_file_typed={source_file_typed} "
               f"load_id_typed={load_id_typed} run_id_coerced={run_id_coerced} "
               f"no_get_default={no_get_default}",
    )


def test_table_path_schema_resolution() -> None:
    """Execute the table_path() helper from the template in isolation and assert
    it resolves both lakehouse modes correctly."""
    if not PY_UTILS_TEMPLATE.is_file():
        _check("table_path() resolves schema-enabled vs classic correctly", False,
               detail=f"missing {PY_UTILS_TEMPLATE}")
        return
    src = _notebook_source(_load_ipynb(PY_UTILS_TEMPLATE))
    m = re.search(r"(def\s+table_path\s*\(.*?)(?=\ndef\s|\Z)", src, re.DOTALL)
    if not m:
        _check("table_path() resolves schema-enabled vs classic correctly", False,
               detail="table_path def not found")
        return
    ns: dict = {}
    try:
        exec(m.group(1), ns)  # noqa: S102 - controlled template source under test
        schema_enabled = ns["table_path"]("bronze_x", schema_enabled=True)
        classic = ns["table_path"]("bronze_x", schema_enabled=False)
    except Exception as e:  # noqa: BLE001
        _check("table_path() resolves schema-enabled vs classic correctly", False,
               detail=f"exec error: {e}")
        return
    ok = schema_enabled.endswith("Tables/dbo/bronze_x") and classic.endswith("Tables/bronze_x")
    _check("table_path() resolves schema-enabled vs classic correctly", ok,
           detail=f"schema_enabled={schema_enabled!r} classic={classic!r}")


def test_style_guide_bans_fs_ls_for_files() -> None:
    ok = STYLE_REF.is_file()
    text = STYLE_REF.read_text(encoding="utf-8").lower() if ok else ""
    mentions_fs_ls = "fs.ls" in text
    mentions_mount = "/lakehouse/default/" in text
    _check(
        "python-style-guide.md documents the mount-not-fs.ls file I/O rule",
        ok and mentions_fs_ls and mentions_mount,
        detail=f"exists={ok} fs.ls={mentions_fs_ls} mount={mentions_mount}",
    )


def test_initializer_python_scaffolds_python_utils() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        proc = _run_initializer(target, engine="python")
        utils_dir = target / "3 - Notebooks" / "utilities"
        ipynb = utils_dir / "nb_utils_config.ipynb"
        py = utils_dir / "nb_utils_config.py"
        ok = proc.returncode == 0 and ipynb.is_file() and not py.is_file()
        is_python = False
        if ipynb.is_file():
            try:
                src = _notebook_source(_load_ipynb(ipynb))
                is_python = "import polars" in src and "from pyspark" not in src
            except Exception:  # noqa: BLE001
                is_python = False
        _check("--engine python scaffolds a Python (polars) nb_utils_config.ipynb",
               ok and is_python,
               detail=f"rc={proc.returncode} ipynb={ipynb.is_file()} "
                      f"py_absent={not py.is_file()} python_src={is_python} "
                      f"stderr={proc.stderr[-200:]}")


def test_initializer_pyspark_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        proc = _run_initializer(target, engine="pyspark")
        utils_dir = target / "3 - Notebooks" / "utilities"
        py = utils_dir / "nb_utils_config.py"
        ipynb = utils_dir / "nb_utils_config.ipynb"
        ok = proc.returncode == 0 and py.is_file() and not ipynb.is_file()
        is_pyspark = False
        if py.is_file():
            content = py.read_text(encoding="utf-8")
            is_pyspark = "from pyspark.sql import functions as F" in content
        _check("--engine pyspark still scaffolds the PySpark nb_utils_config.py",
               ok and is_pyspark,
               detail=f"rc={proc.returncode} py={py.is_file()} "
                      f"ipynb_absent={not ipynb.is_file()} pyspark_src={is_pyspark}")


def test_no_local_paths_in_refs() -> None:
    forbidden = [r"C:\\", "/home/", "~/.claude"]
    targets = [META_REF, STYLE_REF, DELTA_REF, PY_UTILS_TEMPLATE]
    offenders: list[str] = []
    for path in targets:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}:{token!r}")
    _check("no local absolute paths in new reference/template files",
           not offenders, detail=f"offenders={offenders}")


def main() -> int:
    test_python_metadata_reference_matches_confirmed()
    test_python_builders_agree_on_metadata_shell()
    test_utils_notebook_valid_ipynb()
    test_utils_defines_required_helpers()
    test_utils_defines_delta_write_kwargs_shim()
    test_add_bronze_metadata_avoids_null_dtype()
    test_table_path_schema_resolution()
    test_style_guide_bans_fs_ls_for_files()
    test_initializer_python_scaffolds_python_utils()
    test_initializer_pyspark_unchanged()
    test_no_local_paths_in_refs()

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
