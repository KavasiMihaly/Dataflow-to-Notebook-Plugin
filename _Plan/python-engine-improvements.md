# Plan: Python-engine improvements (post-integration findings)

**Status:** IMP-1..IMP-5 ✅ DONE (2026-06-08). IMP-6 outstanding — design decision, **grill before coding** (changes the bronze contract).
**Created:** 2026-06-08
**Parent epic:** Python engine (`_Plan/python-notebook-engine.md` — Slices 0–7 complete)
**Source:** the offline integration pass run 2026-06-08 (real `fabric-bronze-builder` + `fabric-silver-builder` on bundled `Sample Education Data`, `engine=python`). See `_Plan/python-notebook-engine.md` § "Integration pass — RAN 2026-06-08".

## Context for the next session (read this first)

The Python notebook engine is **feature-complete and the end-to-end chain works** — a real run produced valid `nb_bronze_*.ipynb` + `nb_silver_*.ipynb` (jupyter kernel, `jupyter_python`, correct bindings, bronze append+merge, silver read_bronze-only+overwrite, syntax-clean), and the engine-aware hook is live (allows clean silver, blocks injected external reads). The PySpark path is byte-for-byte unchanged.

What this plan fixes is the **gap between the unit goldens (clean single-level inline M) and real builder/converter behaviour on messy real M**. None of these block the happy path; #1 is the only one that produces actually-broken output if a user bypasses the LLM builder.

**TDD is mandatory** (global rule): every item below lists the failing test to write first. Keep all existing suites green (`tests/test_*` + `tests/preshipment_audit.py`) and keep the **PySpark path byte-for-byte unchanged** after every change.

---

## How to reproduce the integration pass (runbook)

Run from the repo root. Produces a throwaway scaffold under `_Test/py-integration/` (delete with `rm -rf "_Test/py-integration"` when done).

1. **Scaffold** (`engine=python`):
   `python "skills/fabric-project-initializer/scripts/initialize_fabric_project.py" --target "_Test/py-integration" --name "Py Integration" --workspace "Dev" --engine python --bronze-lakehouse lh_bronze --silver-lakehouse lh_silver --description "integration" --force`
2. **Extract** sample M:
   `python "skills/dataflow-gen1-extractor/scripts/extract_m_from_json.py" --source "examples/sample-dataflows" --output "_Test/py-integration/2 - Source Files/m_queries"`
   (yields 5 queries; `Schools` is the rich one — join + nested if/then/else.)
3. **Convert** real M:
   `python "skills/m-to-pyspark-converter/scripts/convert_m_to_pyspark.py" --m-file "_Test/py-integration/2 - Source Files/m_queries/Sample Education Data/Schools.pq" --target python`
4. **Build for real:** spawn `fabric-dataflow-migration-toolkit:fabric-bronze-builder:fabric-bronze-builder` then `:fabric-silver-builder:` (foreground — they need Bash) with orchestrator-style `engine=python` prompts pointing at the scaffold. They write `.ipynb`; the live hook validates on Write.
5. **Verify** independently: parse each `.ipynb`, `compile()` every code cell (catches syntax bugs), check kernel/`jupyter_python`/binding/write-idiom, and pipe each notebook through `hooks/validate-fabric-structure.py` via stdin (`{tool_name:"Write", tool_input:{file_path, content}}`) — clean silver must defer, an injected `pl.read_csv("Files/…")` must `block`.

---

## Work items (priority order)

### IMP-1 — Converter nested `if/then/else` emits invalid Python  **[High]** — ✅ DONE (2026-06-08)

**Resolution:** added `_convert_if_chain()` to both `polars_generator.py` and `pyspark_generator.py` — it iterates over nested `else if`, emitting a full `.when().then()...otherwise()` chain (polars) / `F.when(c, v).when(...).otherwise(e)` chain (PySpark). Hardened both `_convert_value()` fallbacks to escape quotes/backslashes so no value can break Python syntax. Single-level `if` output is byte-identical to before (PySpark path intact). Regression tests added (`test_python_nested_if_chain_compiles`, `test_pyspark_nested_if_chain_compiles`) asserting the full chain + `compile()`. Verified end-to-end on the bundled `Schools.pq` → raw output now `compile()`s.



**Problem:** `polars_generator` converts only the first condition of a nested M `if/then/else`. The remainder is dumped into `pl.lit("…")` with **unescaped double quotes** → a Python `SyntaxError`.

**Evidence (real output, `Schools.Ofsted Rank`):**
```python
df = df.with_columns((pl.when((pl.col("Ofsted Rating") == "Outstanding")).then(pl.lit(1))
  .otherwise(pl.lit("if [Ofsted Rating] = "Good" then 2 else if ... else null"))).alias("Ofsted Rank"))
```
Correct target (the LLM builder produced this — the emitter should too):
```python
pl.when(pl.col("Ofsted Rating")=="Outstanding").then(pl.lit(1))
  .when(pl.col("Ofsted Rating")=="Good").then(pl.lit(2))
  .when(pl.col("Ofsted Rating")=="Requires improvement").then(pl.lit(3))
  .otherwise(pl.lit(None)).alias("Ofsted Rank")
```
**Fix:** make the if/then/else handler in `skills/m-to-pyspark-converter/scripts/polars_generator.py` **recurse** on the `else` branch, chaining `.when().then()` and terminating in `.otherwise()`. **Also check `pyspark_generator.py`** for the same nested-if gap (likely present — fix both targets).
**Files:** `skills/m-to-pyspark-converter/scripts/polars_generator.py`, possibly `pyspark_generator.py`, `function_map.py`.
**Tests (write first):** extend `tests/test_converter_python_target.py` — a 3-level nested-if case asserting the full `.when().then()` chain AND that the emitted cell `compile()`s (no SyntaxError). Add the equivalent PySpark-target case if that emitter is also fixed.

### IMP-2 — Gate/validator asserts literal `mode="append"`; real builders use a variable  **[Med]** — ✅ DONE (2026-06-08)

**Resolution:** added a `_write_mode_resolves_to(src, expected)` helper to `test_bronze_python.py` and `test_silver_python.py` — accepts both the literal (`mode="append"`) and parameterised (`mode=load_mode` with `load_mode = "append"`) forms; a negative lookbehind keeps `schema_mode="..."` from matching. New test `test_bronze_python_append_via_variable` covers the variable append + guards that overwrite is not mis-read as append. Loosened the validator `agent.md` wording (Python bronze/silver + PySpark bronze/silver) to "resolve the variable before judging — only a non-matching mode is a FAIL." Silver bronze-only contract left untouched/unweakened.



**Problem:** the Slice-6 validator wording + the bronze golden assert the literal `mode="append"`. The real builder emitted `mode=load_mode` where `load_mode="append"` — functionally correct, but a literal-string assertion misses it. Brittle gate = false confidence.
**Fix:** loosen the validator/test to accept `mode=<identifier>` resolving to append/overwrite (or a regex `mode\s*=\s*("append"|append|load_mode|write_mode)`), OR standardise builders to emit the literal. Prefer accepting both — builders legitimately parameterise.
**Files:** `agents/fabric-pipeline-validator/agent.md`, `tests/test_bronze_python.py` (and any gate test asserting the literal).
**Tests (write first):** a bronze fixture using `mode=load_mode` (with `load_mode="append"`) must PASS the write-idiom check.

### IMP-3 — Converter mislabels layer + hardcodes `overwrite`  **[Med]** — ✅ DONE (2026-06-08)

**Resolution (polars target only — PySpark emitter untouched to keep it byte-for-byte):** `polars_generator.py` header is now layer-neutral (`# Converted query: <name>`, no `nb_bronze_` title) and documents that `table_path()`/`read_bronze()` come from `%run utilities/nb_utils_config`. The write block emits `write_mode`/`schema_write_mode` variables defaulting to overwrite, with a clear `# TODO: builder sets layer write mode` marker, so it stays runnable AND flags that the bronze/silver builder overrides it. New test `test_python_converter_is_layer_agnostic`.



**Problem:** converter output is titled `nb_bronze_*` yet emits `mode="overwrite"` and calls `table_path()` without defining/importing it — misleading as a standalone snippet (builders override correctly).
**Fix:** the converter is layer-agnostic — drop the `nb_bronze_`/`write_deltalake(... overwrite ...)` assumptions from the emitter, or make the write idiom a clearly-marked `# TODO: builder sets layer write mode` placeholder. Keep `table_path()` usage but add a header comment that it comes from `%run utilities/nb_utils_config`.
**Files:** `skills/m-to-pyspark-converter/scripts/polars_generator.py`.
**Tests (write first):** assert the converter does not hardcode a layer-specific write mode (or emits the documented placeholder).

### IMP-4 — Builders disagree on notebook metadata shell  **[Low]** — ✅ DONE (2026-06-08)

**Resolution:** the bronze `agent.md` previously described the Python metadata in prose (only the two discriminator fields); replaced with the explicit canonical JSON block (all four fields: `kernel_info`, `kernelspec`, `language_info`, `microsoft`) bound to the bronze lakehouse — byte-identical to silver's block except the binding. Silver `agent.md` annotated to match. New regression test `test_python_builders_agree_on_metadata_shell` pins both Python goldens (+ utils template) to one `CANONICAL_SHELL` (`kernel_info.name`/`kernelspec.name`=jupyter, `display_name`=Jupyter, `language_group`=jupyter_python). The open `spark_compute`/`nteract` deploy micro-question still rides with the deferred live-Fabric round-trip.



**Problem:** bronze builder wrote `kernelspec.name="jupyter"`; silver wrote `kernelspec.name="python3"` (both carry the correct `microsoft.language_group: "jupyter_python"`). Inconsistent shells risk deploy surprises.
**Fix:** point both builder `agent.md`s at the single canonical block in `reference/python-notebook-metadata.md` (the Slice-0 confirmed export) and state it verbatim. Resolve the open micro-question "does omitting `spark_compute`/`nteract` affect deploy?" during the live-Fabric round-trip.
**Files:** `agents/fabric-bronze-builder/agent.md`, `agents/fabric-silver-builder/agent.md`, `reference/python-notebook-metadata.md`.
**Tests (write first):** a structural test (or extend `test_bronze_python`/`test_silver_python`) asserting both engines' goldens carry identical `kernelspec` + `microsoft.language_group`.

### IMP-5 — Converter `--output FILE` mishandles the path  **[Low]** — ✅ DONE (2026-06-08)

**Root cause:** there was no `--output` flag — argparse prefix-matched `--output` onto `--output-dir`, so the file path became a directory. **Resolution:** added an explicit `--output FILE` argument + `write_output_file()` helper (writes the exact path, creates parent dirs) wired into the single-query handlers (`--m-file`, `--m-code`, single-table `--tmdl-file`). Guarded against `--output` with multi-table `--tmdl-path`/multi-partition `--tmdl-file` (errors, points to `--output-dir`). New test `test_cli_output_writes_exact_file`.



**Problem:** `convert_m_to_pyspark.py --output <file>` treats the path as a directory (wrote `<file>\nb_*.py`).
**Fix:** honour `--output` as a file path when it has a `.py` suffix / parent dir exists; only treat as a dir when it is one.
**Files:** `skills/m-to-pyspark-converter/scripts/convert_m_to_pyspark.py`.
**Tests (write first):** `--output some/dir/out.py` writes exactly `out.py`.

### IMP-6 — Single ingest+join M query places the join in bronze  **[Design — not engine-specific]**

**Problem:** a query that ingests AND joins (e.g. `Schools` joins `Ofsted Rating`) gets the join emitted in the **bronze** notebook → `bronze_schools` reads `bronze_ofsted_rating` (intra-bronze ordering dependency; the builder flagged "no fallback if missing"). Affects BOTH engines — pre-existing pipeline behaviour the integration merely exposed.
**Decision needed (not just a fix):** should the pipeline split such a query into pure-ingest bronze (one table per source) + join-in-silver? That's a bigger architectural change touching the analyst's layer assignment + both builders. **Recommend a `/grill-me` on this before coding** — it changes the bronze contract.
**Files (if pursued):** `agents/migration-analyst/agent.md` (layer assignment), both builders, possibly the orchestrator Section 6.
**Tests:** TBD after the design decision.

### IMP-7 — Bronze builder defaults source read to `parquet`, ignores `Csv.Document`  **[Med]** — ✅ DONE (2026-06-08)

**Problem (surfaced by the 0.6.0 namespaced-builder re-test):** both `Schools` and `Ofsted Rating` source M ingest a **CSV** (`Csv.Document(..., [Delimiter=",", Encoding=65001])`), yet the real bronze builder emitted `source_format = "parquet"` + `pl.read_parquet(source_path)`. The generated bronze notebook would fail at runtime against the actual CSV files. Pre-existing bronze-builder behaviour (the `source_format = "{format}"` template placeholder had no rule telling the builder to derive the format from the M), exposed once the builder followed the template literally. Affects **both engines** (the PySpark `spark.read.format(source_format)` cell has the same placeholder). The deterministic converter (`_gen_source` in `polars_generator.py`/`pyspark_generator.py`) already maps `Csv.Document → read_csv` correctly — no converter change needed.

**Fix:** added a **"Source-format detection (derive from the M — never default)"** rule to `agents/fabric-bronze-builder/agent.md` (engine-agnostic, in Bronze Layer Principles) mapping the M document-parser step to the read idiom (`Csv.Document → csv`, `Parquet.Document → parquet`, `Json.Document → json`, `Excel.Workbook → excel/flag`), clarifying that file *locators* (`AzureStorage.Blobs`, `SharePoint.Files`, `File.Contents`, `Folder.Files`, `Web.Contents`) only locate bytes — the format comes from the wrapping parser — and a hard rule: **never default `source_format` to parquet; if no parser is recognizable, STOP and flag.** Tightened the PySpark Parameters-cell + Python read-section comments to point at the rule. Carry CSV `Delimiter`/`Encoding`/`PromoteHeaders` options through.
**Files:** `agents/fabric-bronze-builder/agent.md` (both engine sections).
**Tests:** agent-instruction change (LLM-driven, not script-unit-testable); validated by re-running the bronze builder on the CSV-sourced samples and confirming `pl.read_csv`/`spark.read.format("csv")` with the right options (see re-test note below).

---

## Still deferred (not in this plan)
- **Live Fabric deploy/run round-trip** for `engine=python` — needs a workspace (epic anti-scope = no notebook execution in CI). Run when online: deploy the produced `.ipynb` via `fab`, confirm it registers as a Python notebook and that `table_path()` writes register the Delta tables (no "Unidentified" stragglers).

## Success criteria for this plan
1. IMP-1: converter emits valid, syntactically-correct nested-if chains on both targets; new regression tests green; PySpark target output otherwise unchanged.
2. IMP-2..5 closed with tests; full offline suite + pre-shipment audit green; PySpark path byte-for-byte unchanged.
3. IMP-6: a recorded design decision (grilled), implemented or explicitly deferred with rationale.
4. Integration runbook re-run after fixes → bronze + silver still valid, hook still live, raw converter output now syntax-clean without builder repair.

## Security
- No new secrets; generated notebooks never embed connection strings (`notebookutils.credentials.getSecret`).
- No local absolute paths in any tracked file (`${CLAUDE_PLUGIN_ROOT}` / placeholders only).
- The silver bronze-only contract must remain enforced (never weakened) through any validator/gate loosening in IMP-2.
