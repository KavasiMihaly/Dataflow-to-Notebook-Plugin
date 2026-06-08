# Plan: Python-notebook engine (PySpark ⇄ Python toggle)

**Status:** Draft — Slices 0–1 complete, Slices 2–7 not started
**Created:** 2026-06-07
**Last updated:** 2026-06-07
**Research:** `_Research/python-notebook-engine-implementation.md` (decision matrix, full PySpark→polars translation reference, gap analysis, confirmed metadata)
**Epic:** Python engine

## Goal

Let a migration emit **100 % Python notebooks** (single-node; polars / duckdb / delta-rs) instead of **100 % PySpark notebooks**, chosen by **one global toggle at the start of the run**, for low-volume solutions — per the [Fabric notebook selection guide](https://learn.microsoft.com/en-us/fabric/data-engineering/fabric-notebook-selection-guide).

Concretely: a user sets `notebook_engine: python`, runs the orchestrator on the sample dataflows, and gets valid **Python-kernel** bronze + silver `.ipynb` notebooks — **while `engine=pyspark` leaves the existing path byte-for-byte unchanged.**

## Why this matters

The Python notebook is a 2-vCore / 16 GB single-node runtime that starts faster and costs less than a Spark cluster — the right tool for the many dataflows that move well under a gigabyte. Today the plugin can only emit PySpark, forcing Spark cluster cost onto low-volume migrations. The toggle closes that gap without touching the proven Spark path.

## Decisions locked (from research — do not re-litigate without flagging)

1. **Toggle = `userConfig.notebook_engine` (default `pyspark`) + orchestrator `--engine python|pyspark` flag.** Asked at Stage 1 if unset; persisted to Section 0 + `project-config.yml`. **One engine per project** (no mixing in v1).
2. **Builders are parameterized by `engine`, not forked.** The two existing builder agents read the engine-appropriate reference set; layer contracts (bronze append-only + metadata; silver bronze-only + overwrite) are engine-independent.
3. **Converter gains `--target python|pyspark`**, sharing the M parser; only the emitter is engine-specific.
4. **No data-driven engine advisory** — the migration pipeline has no source-volume signal (it holds M code, never source rows). The toggle is the user's call; the single-node memory caveat lives in docs + the Stage-7 approval text, not as a gate.
5. **Python kernel metadata CONFIRMED** (Slice 0): kernel `jupyter`, discriminator `microsoft.language_group: "jupyter_python"`, lakehouse-binding block identical to PySpark. See research §8.1.
6. **File I/O in Python notebooks uses the `/lakehouse/default/...` mount** (`os`/`glob`/`pathlib`), NOT `notebookutils.fs.ls` on `abfss://` (live-confirmed 500/timeout). Delta-table reads via `pl.read_delta`/`deltalake` are unaffected.

## Anti-scope

- **No notebook execution in CI.** We assert the *right code is emitted* (valid `.ipynb`, correct kernel, correct write idiom). Executing notebooks against a live lakehouse is the validator's runtime mode, exercised manually when Fabric access is available.
- **No gold layer.** Bronze + silver only, matching today's pipeline.
- **No `--engine` mixing / per-notebook engines.** One engine per project.
- **No new source connectors.** Same sources the PySpark path handles; only the codegen idiom changes.
- **No deprecation of the PySpark path.** PySpark stays the default and the regression baseline.

## Test infrastructure (shared across slices)

- Standalone `tests/test_*.py` runners (matching the repo's existing 4 test files — stdlib `unittest`/asserts, no pytest dependency assumed).
- **Golden-notebook fixtures**: `tests/fixtures/golden/pyspark/*.ipynb` (captured from current output — the regression baseline) and `tests/fixtures/golden/python/*.ipynb` (new expected Python output).
- **`.pq` source fixtures** reused from `tests/fixtures/m_queries/` where they exist.
- Every slice's red phase = write the failing test first, then implement.

---

## Slice 0 — Metadata spike (de-risk) ✅ DONE 2026-06-07

**Goal:** capture the exact Python-notebook `.ipynb` metadata so the template is correct.

**Outcome:** confirmed from a real exported notebook (`_Research/Notebook_Python_Test.ipynb`). Kernel `jupyter`; discriminator `microsoft.language_group: "jupyter_python"`; `dependencies.lakehouse` shape unchanged from PySpark. Recorded in research §8.1.

**Carry-over:** the `fab`-deploy round-trip ("does it deploy as a Python notebook?") is deferred to Slice 3 (needs Fabric; user offline for now).

---

## Slice 1 — Toggle plumbing (offline; PySpark path must stay byte-identical) ✅ DONE 2026-06-08

**Outcome:** `notebook_engine` userConfig added to `plugin.json`; initializer accepts `--engine pyspark|python` (default `pyspark`, unknown rejected) and writes `project.engine` to `project-config.yml`; orchestrator resolves the engine at Stage 1, records it in Section 0, threads `--engine` into the Stage 2 scaffold call, and shows it (with the single-node caveat) in the Stage 7 approval text; README gains the engine decision matrix. **Interim guard:** `engine=python` is recorded + warned about but still emits PySpark until Slices 3–4 — surfaced at Stage 1, Stage 7, and in the README. Tests: `tests/test_engine_toggle.py` (6/6 green), pre-shipment audit + risk-catalog regression green, PySpark config byte-identical to `tests/fixtures/golden/project-config.pyspark.yml`.

**Goal:** introduce `notebook_engine` end-to-end as configuration, with zero behavioural change when it's `pyspark`.

**Scope (in):**
- `.claude-plugin/plugin.json` — add `notebook_engine` userConfig (string; doc: `pyspark` (default) | `python`).
- `agents/fabric-migration-orchestrator/agent.md` — Stage 1 reads `${CLAUDE_PLUGIN_OPTION_notebook_engine}` / `--engine` flag; writes engine to Section 0; Stage 7 approval text states the engine + (for python) the single-node memory caveat.
- `skills/fabric-project-initializer/scripts/initialize_fabric_project.py` — accept `--engine`, write `engine:` into `project-config.yml` (default `pyspark`).
- `README.md` — document the toggle + decision matrix pointer.

**Scope (out):** no builder changes; no reference set; no codegen. `engine=python` is *recorded* but produces the same PySpark notebooks until Slice 3 (acceptable interim — guarded by the approval text noting "Python builders land in a later slice" if we ship incrementally; otherwise hold the user-facing toggle until Slice 4).

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | `project-config.yml` gains `engine` field |
| Processing | initializer `--engine` arg + orchestrator Stage-1 resolution |
| Presentation | Stage-7 approval prints engine + caveat; README decision matrix |
| Test | `tests/test_engine_toggle.py` |

**Tests (TDD red phase — write first):**
1. `test_initializer_default_engine_is_pyspark` — run initializer with no `--engine` → `project-config.yml` has `engine: pyspark`.
2. `test_initializer_engine_python` — `--engine python` → `engine: python`.
3. `test_initializer_rejects_unknown_engine` — `--engine spark3` → non-zero exit, clear error.
4. `test_plugin_json_has_notebook_engine_userconfig` — `plugin.json` parses; `userConfig.notebook_engine` present; description names both values + default.
5. `test_preshipment_audit_still_passes` — run `tests/preshipment_audit.py` → PASS (manifest still valid).
6. `test_pyspark_path_unchanged` — initializer with default engine produces config byte-identical to a pre-change golden (regression guard).

**Success criteria:** engine is configurable + persisted; default is `pyspark`; unknown engines rejected; audit green; no diff in PySpark-default output.

**Security:** no new secrets; `engine` is non-sensitive; no paths embedded.

---

## Slice 2 — Python reference set + utilities notebook (offline)

**Goal:** author the Python-engine knowledge the builders read, plus the runtime helper notebook.

**Scope (in):**
- `reference/python-notebook-metadata.md` — the confirmed metadata block (research §8.1) as the canonical template source.
- `reference/python-style-guide.md` — polars idioms, no-`F.`, OOM-safe defaults (prefer polars/duckdb over pandas), **file I/O via the mount not `fs.ls`** (research §3.3 finding).
- `reference/python-delta-patterns.md` — `write_deltalake`/`polars.write_delta` (append+`schema_mode="merge"`, overwrite+`schema_mode="overwrite"`), delta-rs `merge`, the **`table_path()` resolver** + the "Unidentified table" registration gotcha (research §5).
- Python utilities notebook template `nb_utils_config` (`.ipynb`, jupyter kernel): `read_bronze()`, `add_bronze_metadata()`, `add_silver_metadata()`, `silver_table()`, `table_path()`, `validate_row_count()` in polars/delta-rs.
- `skills/fabric-project-initializer/` — scaffold the Python `nb_utils_config` + copy the Python reference set when `engine=python`.

**Scope (out):** builders don't consume these yet (Slice 3/4).

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | 3 reference `.md` files + 1 utilities `.ipynb` template |
| Processing | initializer branch: engine=python copies Python refs + utils |
| Presentation | reference files are the human-readable guides |
| Test | `tests/test_python_reference_set.py` |

**Tests (TDD red phase):**
1. `test_python_metadata_reference_matches_confirmed` — `reference/python-notebook-metadata.md` contains `"name": "jupyter"` and `"language_group": "jupyter_python"`.
2. `test_utils_notebook_valid_ipynb` — `nb_utils_config` template parses as JSON, `nbformat==4`, non-empty cells, jupyter kernel metadata.
3. `test_utils_defines_required_helpers` — source contains defs for `read_bronze`, `add_bronze_metadata`, `add_silver_metadata`, `silver_table`, `table_path`, `validate_row_count`.
4. `test_table_path_schema_resolution` — unit-test the `table_path()` logic: schema-enabled → `Tables/dbo/<n>`; classic → `Tables/<n>`.
5. `test_style_guide_bans_fs_ls_for_files` — `python-style-guide.md` documents the mount-not-`fs.ls` rule (guards the §3.3 finding against rot).
6. `test_initializer_python_scaffolds_python_utils` — `--engine python` scaffold produces a Python (not PySpark) `nb_utils_config`.
7. `test_initializer_pyspark_unchanged` — `--engine pyspark` still scaffolds the PySpark utils (regression).
8. `test_no_local_paths_in_refs` — none of the new files contain `C:\\`, `/home/`, `~/.claude` (global rule).

**Success criteria:** Python reference set exists, valid, self-consistent with confirmed metadata; `table_path()` handles both lakehouse modes; PySpark scaffold untouched.

**Security:** helpers use `notebookutils.credentials.getSecret` for any secret; no connection strings; no local paths; writes target only the bound lakehouse.

---

## Slice 3 — Python bronze builder path

**Goal:** `engine=python` emits a correct polars + delta-rs bronze notebook.

**Scope (in):**
- `agents/fabric-bronze-builder/agent.md` — broaden description to "PySpark **or** Python"; add an `engine` input; when `python`, read the Python reference set and emit: jupyter-kernel `.ipynb`; read source via polars (CSV/parquet/json) **or** mount for file discovery; metadata cols (`_load_timestamp` via `datetime.now(timezone.utc)`, `_load_id` via `notebookutils.runtime.context`); write via `write_deltalake(table_path(...), arrow, mode="append", schema_mode="merge")`; validation via `validate_row_count()`.
- Orchestrator Stage 8 prompt — pass `engine` into the builder prompt.

**Scope (out):** silver (Slice 4); converter (Slice 5).

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | `.pq`/CSV bronze fixtures (reuse sample dataflows) |
| Processing | engine-aware bronze builder + orchestrator prompt thread |
| Presentation | golden Python bronze `.ipynb` |
| Test | `tests/test_bronze_python.py` |

**Tests (TDD red phase):**
1. `test_bronze_python_valid_ipynb` — output parses, `nbformat==4`, jupyter kernel, `microsoft.language_group=="jupyter_python"`, lakehouse binding present.
2. `test_bronze_python_no_spark_idioms` — no `spark.read`, no `F.`, no `saveAsTable`, no `pyspark` import.
3. `test_bronze_python_append_schema_merge` — write cell uses `mode="append"` + `schema_mode="merge"`.
4. `test_bronze_python_metadata_columns` — `_load_timestamp`, `_source_file`/source literal, `_load_id` added.
5. `test_bronze_python_uses_table_path` — write target goes through `table_path()` (no hard-coded `Tables/...`).
6. `test_bronze_python_passes_structure_hook` — feed output to `validate-fabric-structure.py` → not blocked.
7. `test_bronze_pyspark_regression` — `engine=pyspark` output diff-clean against golden.
8. **(Manual, Fabric)** deploy the golden via `fab`, confirm it registers as a **Python** notebook and writes the Delta table (carries Slice 0's deferred round-trip).

**Success criteria:** valid Python bronze notebook, correct write idiom + metadata, passes the hook; PySpark bronze unchanged.

**Security:** no secrets/connection strings in output; secret access via `notebookutils.credentials`; append-only (no destructive overwrite of raw).

---

## Slice 4 — Python silver builder path

**Goal:** `engine=python` emits a `read_bronze()`-only polars silver notebook.

**Scope (in):**
- `agents/fabric-silver-builder/agent.md` — engine-aware; Python path emits: `%run utilities/nb_utils_config` (notebook item — works in Python per research §3.6); `df = read_bronze("src")`; polars transforms (rename/cast/dedup/decode/unpivot/join per research §4); drop bronze metadata, `add_silver_metadata`; `write_deltalake(..., mode="overwrite", schema_mode="overwrite")`; `validate_row_count`.
- Orchestrator Stage 9 prompt — pass `engine`.

**Scope (out):** converter (Slice 5).

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | bronze→silver fixture pair |
| Processing | engine-aware silver builder + prompt thread |
| Presentation | golden Python silver `.ipynb` |
| Test | `tests/test_silver_python.py` |

**Tests (TDD red phase):**
1. `test_silver_python_valid_ipynb` — valid jupyter-kernel `.ipynb`, `lh_silver` binding.
2. `test_silver_python_read_bronze_only` — exactly one read path, `read_bronze(...)`; **no** `pl.read_csv/read_parquet/scan_delta` of external paths, no `abfss://`/`Files/` literals, no `os.walk`/mount reads of raw.
3. `test_silver_python_overwrite_schema` — write uses `mode="overwrite"` + `schema_mode="overwrite"`.
4. `test_silver_python_metadata_swap` — bronze metadata dropped, `add_silver_metadata` called.
5. `test_silver_python_no_spark_idioms` — no `spark.*`/`F.`/`pyspark`.
6. `test_silver_python_passes_structure_hook_python_branch` — passes the engine-aware hook (Slice 6 dependency; until then, assert against the to-be-added Python forbidden list).
7. `test_silver_pyspark_regression` — PySpark silver diff-clean against golden.
8. **(Integration, `--sample --dry-run`)** bronze (Slice 3) → silver round-trips: silver's `read_bronze` resolves the bronze table written by the Slice-3 notebook (validates the `table_path()` registration handling, research §5).

**Success criteria:** Python silver reads bronze-only, overwrite idiom, metadata swapped, hook-clean; PySpark silver unchanged.

**Security:** silver never reads external storage (contract preserved across engines); no secrets in output.

---

## Slice 5 — M→Python converter

**Goal:** `m-to-pyspark-converter` gains `--target python|pyspark`, emitting polars from the same M parse.

**Scope (in):**
- `skills/m-to-pyspark-converter/` — add `--target` flag; new polars emitter mapping the table/expression/type tables from research §4; rename skill description to cover both targets (keep skill name for compatibility, or alias).
- Mapping coverage: the 17 table ops + expression patterns + the polars type map (research §4).

**Scope (out):** builder integration already done (Slice 3/4 call the converter with `--target`).

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | M fixtures (reuse the converter's existing regression fixtures) |
| Processing | polars emitter + `--target` dispatch |
| Presentation | generated polars snippets |
| Test | extend `tests/` converter regression with polars-target expectations |

**Tests (TDD red phase):**
1. `test_target_pyspark_unchanged` — `--target pyspark` (default) output diff-clean vs current goldens (no regression).
2. `test_target_python_table_ops` — each mapped M table op → expected polars (`Table.SelectRows`→`.filter`, `Table.RenameColumns`→`.rename`, `Table.TransformColumnTypes`→`.cast`, `Table.Group`→`.group_by().agg`, `Table.NestedJoin`+`Expand`→`.join`, unpivot/pivot, distinct, combine).
3. `test_target_python_type_map` — M types → polars types (`Int64.Type`→`pl.Int64`, `Currency.Type`→`pl.Decimal(19,4)`, etc.).
4. `test_target_python_expressions` — `each [Col]`→`pl.col("Col")`, `if/then/else`→`pl.when().then().otherwise()`, concat, text fns.
5. `test_target_python_unknown_emits_todo` — unsupported M → `# TODO` marker (parity with PySpark behaviour), not a crash.
6. `test_cli_rejects_unknown_target`.

**Success criteria:** both targets emit from one parse; PySpark target unchanged; polars target covers the documented mapping; unknowns degrade to TODO.

**Security:** converter strips connection strings/credentials (existing behaviour) on both targets.

---

## Slice 6 — Engine-aware gates (hook + validator)

**Goal:** the structure hook and pipeline validator enforce the *correct* contract per engine, with no cross-engine leakage.

**Scope (in):**
- `hooks/validate-fabric-structure.py` — engine-detect from notebook metadata (`microsoft.language_group`); Python silver forbidden set = polars/mount external reads (`pl.read_csv/read_parquet/read_delta` of non-bronze, `abfss://`, `Files/`, `os.walk` of raw) while still requiring a `read_bronze` call; keep PySpark branch intact.
- `agents/fabric-pipeline-validator/agent.md` — engine-aware Step-1 contracts: Python bronze = `write_deltalake append` + metadata; Python silver = `read_bronze`-only + overwrite; positively assert `microsoft.language_group=="jupyter_python"` for Python notebooks; row-count check via delta-rs/duckdb, not `spark.table().count()`.
- `tests/preshipment_audit.py` — extend the `notebook_extension`/structure gates if needed to cover both engines.

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | paired PySpark + Python pass/fail notebook fixtures |
| Processing | engine branches in hook + validator |
| Presentation | validator Section-10 wording covers engine |
| Test | `tests/test_engine_aware_gates.py` |

**Tests (TDD red phase):**
1. `test_hook_pyspark_silver_unchanged` — existing PySpark silver fixtures still pass/fail as before.
2. `test_hook_python_silver_external_read_blocked` — Python silver with `pl.read_csv(...)`/`os.walk("Files/...")` → blocked.
3. `test_hook_python_silver_read_bronze_ok` — Python silver via `read_bronze` → allowed.
4. `test_hook_python_bronze_external_read_ok` — Python bronze reading source files → allowed (bronze is the read layer).
5. `test_validator_asserts_python_kernel_group` — Python notebook missing `jupyter_python` → FAIL.
6. `test_validator_python_write_idiom` — Python bronze without `append`, or silver without `overwrite` → FAIL.
7. `test_cross_engine_leak_spark_in_python` — `F.col`/`spark.read` inside a jupyter-kernel notebook → FAIL.
8. `test_cross_engine_leak_python_in_pyspark` — `write_deltalake` inside a synapse_pyspark notebook → FAIL (or WARN per chosen severity).

**Success criteria:** both engines validated correctly; silver bronze-only contract preserved on both; cross-engine idiom leakage caught.

**Security:** the silver "no external reads" guarantee is preserved (not weakened) for the new engine.

---

## Slice 7 — Risk-catalog addendum + docs

**Goal:** make the 30-risk catalog and user docs engine-aware.

**Scope (in):**
- `reference/m-conversion-risk-catalog.md` — add a Python column / addendum: which risks ease in polars (pivot/unpivot, type coercion), which worsen (large-data joins, anything assuming distributed memory), which are Spark-only (VORDER/NEE — N/A in Python).
- `README.md` + `_Documentation/pipeline-workflow.md` — document the toggle, decision matrix, Python limitations (no env vars/Environment item, single-node memory, "some Delta features unsupported").
- `MEMORY.md` — one-line pointer if a durable gotcha emerges.

**Per-layer deliverables:**
| Layer | Deliverable |
|---|---|
| Data | catalog engine annotations |
| Processing | n/a (docs) |
| Presentation | README/workflow toggle docs |
| Test | `tests/test_catalog_engine_addendum.py` |

**Tests (TDD red phase):**
1. `test_catalog_parses_with_engine_column` — catalog still parses under the existing `test_risk_catalog.py` structural rules.
2. `test_every_risk_has_engine_note` — each RISK-NN has a Python applicability note (ease/worsen/N-A/unchanged).
3. `test_readme_documents_toggle` — README contains the decision matrix + `notebook_engine` values.

**Success criteria:** catalog + docs reflect both engines; existing catalog structural tests stay green.

---

## Cross-cutting

### Testing strategy
- **Regression first:** every slice includes a "PySpark path unchanged" assertion against captured goldens. The PySpark path is the contract; it must not move.
- **Offline by default:** Slices 1, 2, 5, 6, 7 fully CI-runnable with no Fabric. Slices 3–4 have one **manual Fabric** check each (deploy round-trip / runtime write) plus offline static checks.
- **Integration gate:** a full `--sample --dry-run` orchestrator run on `engine=python` after Slice 6, diffed against golden Python notebooks, before Slice 7 docs.
- **Pre-shipment audit** (`tests/preshipment_audit.py`) must stay green after every slice.

### Security & safety
- Generated notebooks (both engines) must **never embed connection strings or secrets**; secret access via `notebookutils.credentials.getSecret`.
- No local absolute paths in any tracked reference/template/test fixture (`${CLAUDE_PLUGIN_ROOT}` / lakehouse-relative / placeholders only).
- The **silver bronze-only contract is preserved across engines** — Slice 6 adds, never weakens, enforcement.
- Bronze stays **append-only**; silver overwrite is full-refresh of clean state (unchanged semantics).
- delta-rs writes target only the bound lakehouse path resolved by `table_path()`.
- The structure hook keeps blocking `.py` in `3 - Notebooks/` for both engines (N1 finding stands).

### Overall success criteria
1. `notebook_engine: python` → valid Python-kernel bronze + silver `.ipynb` (correct kernel + `jupyter_python` group + lakehouse binding).
2. Writes land at the correct `Tables[/dbo]/<name>` path with **no "Unidentified" stragglers**; bronze→silver round-trips in one run.
3. Engine-aware hook + validator pass for Python, still pass for PySpark, and catch cross-engine leakage.
4. **`engine=pyspark` output is byte-for-byte unchanged** vs pre-change goldens.
5. Pre-shipment audit green; converter both-target tests green; docs/catalog engine-aware.

### Build order & dependencies
`1 → 2 → {3, 5 in parallel} → 4 → 6 → 7`. Slice 5 (converter) is independent of 3/4's notebook shell and can run alongside. Hold the **user-facing** toggle (Stage-1 prompt) until Slice 4 lands so `engine=python` never silently yields PySpark notebooks — or ship behind the flag only and gate the userConfig surfacing.

### Open micro-questions (low risk; resolve in-slice)
- Does omitting the `spark_compute`/`nteract` blocks on a jupyter notebook affect deploy? (Slice 3 — safest to mirror Fabric's exact export.)
- delta-rs `merge` maturity for any upsert pattern silver needs (Slice 4 — fall back to read-modify-overwrite for small tables).
- Schema-enabled vs classic lakehouse detection source for `table_path()` (`project-config.yml` field set at scaffold; confirm Fabric API exposes it, else ask at Stage 1).
