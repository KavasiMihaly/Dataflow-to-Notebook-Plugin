#!/usr/bin/env python3
"""Slice 1 — notebook_engine toggle plumbing tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.
Matches the repo convention used by test_risk_catalog.py.

Covers the Slice 1 contract from `_Plan/python-notebook-engine.md`:
  - The fabric-project-initializer accepts `--engine`, defaults to `pyspark`,
    persists `engine:` into `project-config.yml`, and rejects unknown engines.
  - `.claude-plugin/plugin.json` exposes a `notebook_engine` userConfig naming
    both values + the default.
  - The pre-shipment audit still passes.
  - The PySpark-default config is byte-identical to the pre-change golden once
    the single `engine:` line is stripped (regression guard — the PySpark path
    must not move).
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
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
AUDIT = ROOT / "tests" / "preshipment_audit.py"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "project-config.pyspark.yml"

FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


def _run_initializer(target: Path, engine: str | None) -> subprocess.CompletedProcess:
    """Invoke the initializer non-interactively into `target`."""
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


def _read_config(target: Path) -> str:
    return (target / "0 - Architecture Setup" / "project-config.yml").read_text(encoding="utf-8")


def _normalize(yml: str) -> str:
    return re.sub(r'created: "[^"]*"', 'created: "<DATE>"', yml)


def _strip_engine_line(yml: str) -> str:
    return "\n".join(
        line for line in yml.splitlines(keepends=False)
        if not re.match(r"\s*engine:\s*", line)
    ) + ("\n" if yml.endswith("\n") else "")


def test_initializer_default_engine_is_pyspark() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        proc = _run_initializer(target, engine=None)
        ok = proc.returncode == 0 and re.search(r'^\s*engine:\s*"pyspark"\s*$',
                                                _read_config(target), re.MULTILINE) is not None
        _check("initializer default engine is pyspark", ok,
               detail=f"rc={proc.returncode} stderr={proc.stderr[-300:]}")


def test_initializer_engine_python() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        proc = _run_initializer(target, engine="python")
        ok = proc.returncode == 0 and re.search(r'^\s*engine:\s*"python"\s*$',
                                                _read_config(target), re.MULTILINE) is not None
        _check("--engine python writes engine: python", ok,
               detail=f"rc={proc.returncode} stderr={proc.stderr[-300:]}")


def test_initializer_rejects_unknown_engine() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        proc = _run_initializer(target, engine="spark3")
        _check("--engine spark3 is rejected with non-zero exit", proc.returncode != 0,
               detail=f"rc={proc.returncode} (expected non-zero)")


def test_plugin_json_has_notebook_engine_userconfig() -> None:
    try:
        manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        _check("plugin.json parses + has notebook_engine userConfig", False, detail=str(e))
        return
    uc = manifest.get("userConfig", {}).get("notebook_engine")
    present = isinstance(uc, dict) and all(k in uc for k in ("title", "description", "type"))
    desc = (uc or {}).get("description", "").lower()
    names_values = present and "pyspark" in desc and "python" in desc and "default" in desc
    _check("plugin.json notebook_engine userConfig names both values + default",
           present and names_values,
           detail=f"present={present} desc={desc[:120]!r}")


def test_preshipment_audit_still_passes() -> None:
    proc = subprocess.run([sys.executable, str(AUDIT)], capture_output=True, text=True, cwd=str(ROOT))
    _check("pre-shipment audit passes", proc.returncode == 0,
           detail=f"rc={proc.returncode} tail={proc.stdout[-400:]}")


def test_pyspark_path_unchanged() -> None:
    """Default-engine config, date-normalized and with the single engine: line
    stripped, must equal the captured pre-change golden byte-for-byte."""
    sys.path.insert(0, str(INITIALIZER.parent))
    import initialize_fabric_project as mod  # type: ignore

    cfg = {
        "display_name": "Sales Analytics",
        "description": "Test fixture project",
        "workspace": "Development",
        "bronze_lakehouse": "lh_bronze",
        "silver_lakehouse": "lh_silver",
        "gold_lakehouse": "lh_gold",
        "engine": "pyspark",
    }
    generated = _strip_engine_line(_normalize(mod.generate_project_config_yml(cfg)))
    golden = GOLDEN.read_text(encoding="utf-8")
    _check("pyspark config byte-identical to pre-change golden (engine line stripped)",
           generated == golden,
           detail="config drifted from golden — see diff" if generated != golden else "")


def main() -> int:
    test_initializer_default_engine_is_pyspark()
    test_initializer_engine_python()
    test_initializer_rejects_unknown_engine()
    test_plugin_json_has_notebook_engine_userconfig()
    test_preshipment_audit_still_passes()
    test_pyspark_path_unchanged()

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
