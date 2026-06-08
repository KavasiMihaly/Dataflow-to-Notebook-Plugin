#!/usr/bin/env python3
"""Slice 5 — M->Python (polars) converter target tests.

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.
Matches the repo convention used by test_risk_catalog.py / test_engine_toggle.py.

Covers the Slice 5 contract from `_Plan/python-notebook-engine.md`:
  1. test_target_pyspark_unchanged   — `--target pyspark` (default) output is
     byte-identical to the pre-Slice-5 PySpark emitter (no regression).
  2. test_target_python_table_ops    — each mapped M table op -> expected polars.
  3. test_target_python_type_map      — M types -> polars types.
  4. test_target_python_expressions   — each [Col]->pl.col, if/then/else->when/then,
     concat, text fns.
  5. test_target_python_unknown_emits_todo — unsupported M -> `# TODO` marker,
     never a crash (parity with PySpark behaviour).
  6. test_cli_rejects_unknown_target  — `--target ruby` -> non-zero exit.

The converter shares the M parser; only the emitter is engine-specific. These
tests drive the polars emitter directly (unit) plus the CLI dispatch
(integration), and pin the PySpark default against the existing emitter so the
proven path cannot move.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
SCRIPTS = ROOT / "skills" / "m-to-pyspark-converter" / "scripts"
CLI = SCRIPTS / "convert_m_to_pyspark.py"

sys.path.insert(0, str(SCRIPTS))

from m_parser import MParser  # noqa: E402
from pyspark_generator import PySparkGenerator  # noqa: E402

FAILURES: list[str] = []

# A 3-level nested M if/then/else (the Schools.Ofsted Rank shape from the
# 2026-06-08 integration pass that exposed IMP-1).
NESTED_IF_M = (
    'let Source = X, '
    'A = Table.AddColumn(Source, "Ofsted Rank", each '
    'if [Ofsted Rating] = "Outstanding" then 1 '
    'else if [Ofsted Rating] = "Good" then 2 '
    'else if [Ofsted Rating] = "Requires improvement" then 3 '
    'else null) in A'
)


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


def _gen_polars(m_code: str, table_name: str = "Query", source: str = "stdin") -> str:
    """Parse M and emit polars via the new PolarsGenerator."""
    from polars_generator import PolarsGenerator  # imported lazily so RED phase is meaningful

    parsed = MParser().parse(m_code)
    return PolarsGenerator().generate(parsed, table_name, source)


# --- 1. PySpark default unchanged --------------------------------------------

def test_target_pyspark_unchanged() -> None:
    """The PySpark emitter output must be identical whether reached via the
    default code path or the new --target dispatch. We assert the generator the
    CLI selects for `pyspark` is still PySparkGenerator and its output is stable
    for a representative multi-step query."""
    m_code = (
        'let\n'
        '  Source = Sql.Database("srv", "db"),\n'
        '  Nav = Source{[Schema="dbo", Item="Sales"]}[Data],\n'
        '  Filtered = Table.SelectRows(Nav, each [Amount] > 0),\n'
        '  Renamed = Table.RenameColumns(Filtered, {{"Amt", "Amount"}}),\n'
        '  Typed = Table.TransformColumnTypes(Renamed, {{"Amount", Currency.Type}})\n'
        'in\n'
        '  Typed'
    )
    parsed = MParser().parse(m_code)
    direct = PySparkGenerator().generate(parsed, "Sales", "Sales.tmdl")

    # Dispatch path: import the CLI's selector and confirm pyspark routes to the
    # PySpark generator with byte-identical output.
    import convert_m_to_pyspark as cli  # noqa: E402

    gen = cli.get_generator("pyspark")
    via_dispatch = gen.generate(MParser().parse(m_code), "Sales", "Sales.tmdl")

    _check("target=pyspark output unchanged vs PySparkGenerator",
           direct == via_dispatch and "from pyspark.sql import functions as F" in direct,
           detail="pyspark dispatch drifted from direct PySparkGenerator output")


# --- 2. Table ops -> polars ---------------------------------------------------

def test_target_python_table_ops() -> None:
    cases = [
        # (label, m_code, list-of-substrings-that-must-appear)
        (
            "SelectRows -> filter",
            'let Source = X, F = Table.SelectRows(Source, each [Amount] > 0) in F',
            ['df = df.filter(', 'pl.col("Amount") > 0'],
        ),
        (
            "RenameColumns -> rename",
            'let Source = X, R = Table.RenameColumns(Source, {{"a", "b"}}) in R',
            ['df = df.rename({"a": "b"})'],
        ),
        (
            "TransformColumnTypes -> cast",
            'let Source = X, T = Table.TransformColumnTypes(Source, {{"Qty", Int64.Type}}) in T',
            ['.with_columns(', 'pl.col("Qty").cast(pl.Int64)'],
        ),
        (
            "Group -> group_by/agg",
            'let Source = X, G = Table.Group(Source, {"Region"}, {{"Total", each List.Sum([Amount]), type number}}) in G',
            ['df.group_by("Region").agg(', 'pl.col("Amount").sum().alias("Total")'],
        ),
        (
            "RemoveColumns -> drop",
            'let Source = X, D = Table.RemoveColumns(Source, {"junk"}) in D',
            ['df = df.drop("junk")'],
        ),
        (
            "SelectColumns -> select",
            'let Source = X, S = Table.SelectColumns(Source, {"keep"}) in S',
            ['df = df.select("keep")'],
        ),
        (
            "Distinct -> unique",
            'let Source = X, D = Table.Distinct(Source) in D',
            ['df = df.unique()'],
        ),
        (
            "Combine -> concat",
            'let Source = X, C = Table.Combine({Other}) in C',
            ['pl.concat('],
        ),
        (
            "Unpivot -> unpivot",
            'let Source = X, U = Table.Unpivot(Source, {"Jan", "Feb"}, "Month", "Val") in U',
            ['df = df.unpivot('],
        ),
        (
            "Sort -> sort",
            'let Source = X, S = Table.Sort(Source, {{"d", Order.Descending}}) in S',
            ['df = df.sort(', 'descending=True'],
        ),
        (
            "NestedJoin + Expand -> join",
            'let Source = X, '
            'J = Table.NestedJoin(Source, {"id"}, Dim, {"id"}, "Dim", JoinKind.Inner), '
            'E = Table.ExpandTableColumn(J, "Dim", {"name"}, {"name"}) in E',
            ['df = df.join(', 'how="inner"'],
        ),
    ]
    for label, m_code, needles in cases:
        try:
            out = _gen_polars(m_code)
            missing = [n for n in needles if n not in out]
            _check(f"table op: {label}", not missing,
                   detail=f"missing {missing!r} in:\n{out}")
        except Exception as e:  # noqa: BLE001
            _check(f"table op: {label}", False, detail=f"raised {e!r}")


# --- 3. Type map --------------------------------------------------------------

def test_target_python_type_map() -> None:
    from polars_generator import PolarsGenerator  # noqa: E402

    g = PolarsGenerator()
    expected = {
        "type text": "pl.Utf8",
        "type number": "pl.Float64",
        "Int64.Type": "pl.Int64",
        "Int32.Type": "pl.Int32",
        "type date": "pl.Date",
        "type datetime": "pl.Datetime",
        "type logical": "pl.Boolean",
        "Currency.Type": "pl.Decimal(19, 4)",
    }
    for m_type, polars_type in expected.items():
        got = g._polars_type(m_type)
        _check(f"type map: {m_type} -> {polars_type}", got == polars_type,
               detail=f"got {got!r}")


# --- 4. Expressions -----------------------------------------------------------

def test_target_python_expressions() -> None:
    cases = [
        (
            "each [Col] -> pl.col",
            'let Source = X, A = Table.AddColumn(Source, "Copy", each [Original]) in A',
            ['pl.col("Original")'],
        ),
        (
            "if/then/else -> when/then/otherwise",
            'let Source = X, A = Table.AddColumn(Source, "Flag", each if [N] > 0 then "pos" else "neg") in A',
            ['pl.when(', '.then(', '.otherwise('],
        ),
        (
            "concat -> pl.concat_str",
            'let Source = X, A = Table.AddColumn(Source, "Full", each [First] & [Last]) in A',
            ['pl.concat_str('],
        ),
        (
            "Text.Upper -> str.to_uppercase",
            'let Source = X, A = Table.AddColumn(Source, "U", each Text.Upper([Name])) in A',
            ['.str.to_uppercase()'],
        ),
    ]
    for label, m_code, needles in cases:
        try:
            out = _gen_polars(m_code)
            missing = [n for n in needles if n not in out]
            _check(f"expression: {label}", not missing,
                   detail=f"missing {missing!r} in:\n{out}")
        except Exception as e:  # noqa: BLE001
            _check(f"expression: {label}", False, detail=f"raised {e!r}")


# --- 4b. Nested if/then/else (IMP-1) -----------------------------------------

def test_python_nested_if_chain_compiles() -> None:
    """A multi-level M `if ... else if ... else` must emit a full chained
    pl.when().then()...otherwise() expression — and the emitted code must
    compile() (no SyntaxError from the else branch being dumped into a string
    literal with unescaped quotes). Regression for IMP-1."""
    try:
        out = _gen_polars(NESTED_IF_M)
    except Exception as e:  # noqa: BLE001
        _check("polars nested-if: generates without crash", False, detail=f"raised {e!r}")
        return

    # The whole chain must be present: 3 conditions, 3 then-values, one otherwise.
    needles = [
        'pl.when((pl.col("Ofsted Rating") == "Outstanding")).then(pl.lit(1))',
        '.when((pl.col("Ofsted Rating") == "Good")).then(pl.lit(2))',
        '.when((pl.col("Ofsted Rating") == "Requires improvement")).then(pl.lit(3))',
        '.otherwise(pl.lit(None))',
    ]
    missing = [n for n in needles if n not in out]
    _check("polars nested-if: full when/then chain emitted", not missing,
           detail=f"missing {missing!r} in:\n{out}")

    # No leftover raw M ('then'/'else if') should survive into executable code.
    leaked = any(
        ("else if" in line or " then " in line)
        for line in out.splitlines()
        if not line.lstrip().startswith("#")
    )
    _check("polars nested-if: no raw M leaks into code", not leaked,
           detail=f"raw M survived in:\n{out}")

    try:
        compile(out, "<nested-if-polars>", "exec")
        _check("polars nested-if: emitted code compiles", True)
    except SyntaxError as e:
        _check("polars nested-if: emitted code compiles", False, detail=f"SyntaxError: {e}")


def test_pyspark_nested_if_chain_compiles() -> None:
    """The PySpark target must also chain F.when().when().otherwise() for a
    nested M if/then/else and compile cleanly. Regression for IMP-1."""
    try:
        out = PySparkGenerator().generate(MParser().parse(NESTED_IF_M), "Schools", "Schools.tmdl")
    except Exception as e:  # noqa: BLE001
        _check("pyspark nested-if: generates without crash", False, detail=f"raised {e!r}")
        return

    needles = [
        'F.when((F.col("Ofsted Rating") == "Outstanding"), F.lit(1))',
        '.when((F.col("Ofsted Rating") == "Good"), F.lit(2))',
        '.when((F.col("Ofsted Rating") == "Requires improvement"), F.lit(3))',
        '.otherwise(F.lit(None))',
    ]
    missing = [n for n in needles if n not in out]
    _check("pyspark nested-if: full when chain emitted", not missing,
           detail=f"missing {missing!r} in:\n{out}")

    try:
        compile(out, "<nested-if-pyspark>", "exec")
        _check("pyspark nested-if: emitted code compiles", True)
    except SyntaxError as e:
        _check("pyspark nested-if: emitted code compiles", False, detail=f"SyntaxError: {e}")


# --- 4c. Layer-agnostic converter output (IMP-3) -----------------------------

def test_python_converter_is_layer_agnostic() -> None:
    """The converter is layer-agnostic — the bronze/silver builders set the
    real layer write mode. Its raw output must NOT (a) title itself
    `nb_bronze_*` or (b) silently hardcode a layer-specific write mode with no
    marker. It MUST flag that the write mode is a builder-overridden default and
    document where table_path() comes from. Regression for IMP-3."""
    out = _gen_polars(
        'let Source = Csv.Document(File.Contents("x.csv")), '
        'F = Table.SelectRows(Source, each [n] > 0) in F',
        table_name="Schools",
    )
    lines = out.splitlines()

    # (a) No bronze-specific notebook title.
    no_bronze_title = not any(l.strip().startswith("# Notebook: nb_bronze_") for l in lines)
    _check("converter header is layer-neutral (no nb_bronze_ title)",
           no_bronze_title, detail=f"found a nb_bronze_ title in:\n{out}")

    # (b) The write mode is explicitly marked as builder-overridden, not a silent
    #     hardcoded layer choice.
    has_marker = ("builder sets" in out) or ("layer write mode" in out)
    _check("converter marks the write mode as builder-overridden",
           has_marker, detail=f"no builder-override marker near write in:\n{out}")

    # (c) table_path() provenance documented (comes from the utilities notebook).
    documents_table_path = "nb_utils_config" in out or "%run" in out
    _check("converter documents table_path() provenance (%run utilities)",
           documents_table_path, detail=f"no table_path provenance note in:\n{out}")

    # Still syntactically valid.
    try:
        compile(out, "<layer-agnostic>", "exec")
        _check("layer-agnostic converter output compiles", True)
    except SyntaxError as e:
        _check("layer-agnostic converter output compiles", False, detail=f"SyntaxError: {e}")


# --- 5. Unknown -> TODO (no crash) -------------------------------------------

def test_target_python_unknown_emits_todo() -> None:
    m_code = 'let Source = X, Weird = Table.FuzzyNestedJoin(Source, SomeMagic) in Weird'
    try:
        out = _gen_polars(m_code)
        _check("unknown M emits # TODO and does not crash",
               "# TODO" in out,
               detail=f"no TODO marker in:\n{out}")
    except Exception as e:  # noqa: BLE001
        _check("unknown M emits # TODO and does not crash", False, detail=f"raised {e!r}")


# --- 6. CLI rejects unknown target -------------------------------------------

def test_cli_rejects_unknown_target() -> None:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--m-code", "let Source = X in Source", "--target", "ruby"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    _check("--target ruby rejected with non-zero exit", proc.returncode != 0,
           detail=f"rc={proc.returncode} (expected non-zero)")


# --- 6b. --output is a FILE path, not a directory (IMP-5) --------------------

def test_cli_output_writes_exact_file() -> None:
    """`--output some/dir/out.py` must write exactly out.py (a file), not a
    directory named out.py containing nb_<query>.py. Regression for IMP-5 (the
    path was previously consumed by --output-dir via argparse prefix matching)."""
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "nested" / "out.py"
        proc = subprocess.run(
            [sys.executable, str(CLI),
             "--m-code", "let Source = X in Source",
             "--target", "python",
             "--output", str(out_path)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        ok = (
            proc.returncode == 0
            and out_path.is_file()
            and not out_path.is_dir()
        )
        _check("--output writes exactly the named .py file",
               ok,
               detail=f"rc={proc.returncode} is_file={out_path.is_file()} "
                      f"is_dir={out_path.is_dir()} stderr={proc.stderr[-200:]}")
        if out_path.is_file():
            content = out_path.read_text(encoding="utf-8")
            _check("--output file holds the converted code",
                   "import polars as pl" in content,
                   detail="converted polars code not found in output file")


# --- bonus: security parity (no connection strings leak on python target) ----

def test_python_target_strips_connection_strings() -> None:
    m_code = 'let Source = Sql.Database("secret-server.example.com", "ProdDB") in Source'
    try:
        out = _gen_polars(m_code, "Sales", "Sales.tmdl")
        # The server/db may appear only inside a comment, never in executable code.
        leaked = False
        for line in out.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "secret-server.example.com" in line or '"ProdDB"' in line:
                leaked = True
        _check("python target keeps connection strings out of executable code",
               not leaked, detail="connection string leaked into a non-comment line")
    except Exception as e:  # noqa: BLE001
        _check("python target keeps connection strings out of executable code",
               False, detail=f"raised {e!r}")


def main() -> int:
    test_target_pyspark_unchanged()
    test_target_python_table_ops()
    test_target_python_type_map()
    test_target_python_expressions()
    test_python_nested_if_chain_compiles()
    test_pyspark_nested_if_chain_compiles()
    test_python_converter_is_layer_agnostic()
    test_target_python_unknown_emits_todo()
    test_cli_rejects_unknown_target()
    test_cli_output_writes_exact_file()
    test_python_target_strips_connection_strings()

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
