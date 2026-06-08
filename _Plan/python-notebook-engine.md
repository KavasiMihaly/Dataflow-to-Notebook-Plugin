# Plan: Python-notebook engine (PySpark ⇄ Python toggle)

**Status:** ✅ All slices (0–7) complete 2026-06-08. Engine toggle, Python reference set + utils, Python bronze + silver builders, M→Python converter, engine-aware gates, and docs/catalog all landed. Orchestrator Stage 1/7 warnings + Stage 8/9 prompts are engine-aware. **Remaining (manual, offline-deferred):** the live Fabric deploy/run round-trip for `engine=python` (epic anti-scope = no notebook execution in CI). Full offline test suite green; PySpark path byte-for-byte unchanged.
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

## Slice 2 — Python reference set + utilities notebook (offline) ✅ DONE 2026-06-08

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

**Outcome note (2026-06-08, Slice 2 implementation):**
- **Files created:** `reference/python-notebook-metadata.md`, `reference/python-style-guide.md`, `reference/python-delta-patterns.md`, `skills/fabric-project-initializer/templates/nb_utils_config_python.ipynb`, `tests/test_python_reference_set.py`. **Edited:** `skills/fabric-project-initializer/scripts/initialize_fabric_project.py` (added `create_python_utility_notebook()` + an engine branch in `main()`'s Step 2).
- **All 8 Slice-2 tests green** (RED→GREEN verified). Regression: `preshipment_audit.py`, `test_engine_toggle.py`, `test_risk_catalog.py` all stay green; PySpark scaffold path untouched (test 7).
- **Decision — utils-notebook placement:** template lives at `skills/fabric-project-initializer/templates/nb_utils_config_python.ipynb` (mirrors the existing `templates/fabric-CLAUDE.md` convention; the initializer substitutes `__PLACEHOLDER__` tokens and writes the scaffolded copy to `3 - Notebooks/utilities/nb_utils_config.ipynb`). The PySpark `.py` utility is **not** written when `engine=python` (one engine per project).
- **Decision — `table_path()` schema-detection source:** `project-config.yml` (`medallion.layers.*.schema_enabled`), surfaced into a module-level `SCHEMA_ENABLED` constant in the utils notebook. **Default `False` (classic lakehouse)** — the safe default per research §5 (a classic path under a classic lakehouse always registers; schema-enabled lakehouses set it `True` to write under `Tables/dbo/<name>`). `table_path(name, schema_enabled=None)` falls back to `SCHEMA_ENABLED` when the kwarg is omitted, and accepts an explicit override (unit-tested both ways).
- **Decision — metadata block:** mirror Fabric's full export verbatim (keep the harmless `spark_compute` + `nteract` residue rather than stripping) — lowest-risk; the "is stripping `spark_compute` safe?" micro-question stays deferred to the Slice 3 `fab`-deploy round-trip. Templated `jupyter_kernel_name` = `python3.11` (documented Fabric default; informational, Fabric adjusts on deploy).
- **Decision — lakehouse-id binding:** the scaffolded notebook's `dependencies.lakehouse` uses readable placeholders (`<bronze-lakehouse-id>`, `<workspace-id>`) offline — no fake GUIDs ship; bound at Fabric deploy time. Bronze lakehouse is bound by default in the utils notebook (matches the PySpark default-lakehouse convention).
- **Decision — `add_silver_metadata`:** drops bronze ingestion cols (`_load_timestamp`/`_source_file`/`_load_id`) and stamps `_silver_processed_timestamp` (the bronze→silver metadata swap the silver contract needs in Slice 4).
- **Auto-copy confirmed:** the 3 new `reference/*.md` files ship into a scaffolded project automatically via the existing `create_agentic_resources()` (copies the whole `reference/` folder) — no initializer change needed for the refs.
- **Deferred (unchanged from plan):** builders don't consume these yet (Slice 3/4); `fab`-deploy round-trip + delta-rs merge maturity (Slice 3/4); the `spark_compute`-stripping micro-question.

---

## Slice 3 — Python bronze builder path ✅ DONE 2026-06-08

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

### Outcome note (implementation pass 2026-06-08 — NOT marked Done; main agent to confirm)

**Status:** implemented + tests 1–7 green; test 8 deferred-manual (Fabric) as a documented no-op skip. Left for the main agent to mark Done.

**Files created:**
- NEW `tests/test_bronze_python.py` — the 8 Slice-3 tests (1–7 automated, 8 documented manual skip).
- NEW `tests/fixtures/golden/python/nb_bronze_customers.ipynb` — hand-authored Python bronze exemplar.
- NEW `tests/fixtures/golden/pyspark/nb_bronze_customers.ipynb` — PySpark bronze golden (regression baseline; pinned to the agent.md template).

**Files edited:**
- `agents/fabric-bronze-builder/agent.md` — broadened the frontmatter `description` to "PySpark **or** Python"; added an **Engine input** section + a **Python engine** reference-set block; added a full **Python Engine (`engine=python`)** section (kernel/metadata discriminator, forbidden Spark idioms, mount-not-`fs.ls` file I/O rule, 7-cell Python bronze structure, metadata-column + read + write idioms). **The PySpark "Standard Notebook Cell Structure" / "Notebook Template" / "Import Convention" / "Common Patterns" / "Success Criteria" sections are byte-untouched** — `engine=pyspark` is unchanged (verified by test 7 + `test_engine_toggle`/`preshipment_audit` staying green).

**Tests:** 1 `test_bronze_python_valid_ipynb` ✅ · 2 `test_bronze_python_no_spark_idioms` ✅ · 3 `test_bronze_python_append_schema_merge` ✅ · 4 `test_bronze_python_metadata_columns` ✅ · 5 `test_bronze_python_uses_table_path` ✅ · 6 `test_bronze_python_passes_structure_hook` ✅ · 7 `test_bronze_pyspark_regression` ✅ · 8 `test_bronze_python_fabric_deploy_roundtrip_MANUAL` ⏭ deferred-manual skip. RED→GREEN verified (the 6 Python tests fail with the golden absent; PySpark + manual independent). Regressions green: `preshipment_audit`, `test_engine_toggle`, `test_python_reference_set`.

**Default decisions made (documented inline in the test/golden/agent):**
- **Golden-capture approach:** an LLM-authored builder's exact output is not script-reproducible, so the goldens are **hand-authored exemplars** embodying the documented output, and the tests assert **structural properties** (kernel discriminator, forbidden-idiom absence, write idiom, metadata cols, `table_path()` usage, hook-clean) rather than byte-equality of the LLM output. Test 7 *does* pin the PySpark golden's write idiom + metadata + imports to the `agent.md` template verbatim so the PySpark path cannot silently drift.
- **Exact bronze write idiom emitted:** `write_deltalake(table_path(f"bronze_{source_name}"), df_bronze.to_arrow(), mode="append", schema_mode="merge")` — delta-rs append + schema merge, path resolved through `table_path()` (no hard-coded `Tables/...`).
- **Helpers source:** the Python bronze notebook gets `table_path()` / `validate_row_count()` via `%run utilities/nb_utils_config` (Slice-2 contract, signatures used exactly). The golden inlines the metadata columns directly (`add_bronze_metadata()` available from the utils notebook; the literal idiom is shown explicitly so the test can assert the three columns + UTC + run-context).
- **Source read:** files discovered via `glob` over the `/lakehouse/default/Files/...` mount (NOT `notebookutils.fs.ls`), read with `pl.read_csv` + `pl.concat(..., how="diagonal_relaxed")` for multi-file; Parquet/JSON variants documented in the agent.
- **`_source_file`:** single-node has no per-row `input_file_name()`, so it's the **resolved source-path literal** (`pl.lit(source_path)`), matching the Slice-2 `add_bronze_metadata(source_file=...)` signature intent.
- **Kernel metadata:** mirrors Fabric's full export verbatim (keeps `spark_compute`/`nteract` residue) per the Slice-2 decision; both discriminators (`kernel_info.name=="jupyter"` + `microsoft.language_group=="jupyter_python"`) set; bronze lakehouse bound via readable placeholders (no fake GUIDs).
- **Hook test:** feeds the golden through the live `validate-fabric-structure.py` as a `Write` PreToolUse payload on a `3 - Notebooks/bronze/` path; the hook's `_validate_ipynb_shape` (valid JSON, nbformat 4, non-empty cells, lakehouse binding) passes and the bronze branch does not block. (The hook does not check kernel today — that positive `jupyter_python` assertion lands in Slice 6's validator, as noted in `python-notebook-metadata.md`.)

**Deferred:**
- **Test 8 (Fabric deploy round-trip)** — carries Slice 0's deferred `fab`-deploy check (confirm Fabric registers the notebook as a *Python* notebook + writes the Delta table). Requires Fabric; run manually when online. Implemented as a no-op skip per the epic anti-scope "no notebook execution in CI".
- **Orchestrator Stage 8 prompt thread** (`engine` into the builder prompt) is OUT of this pass's territory — the MAIN agent owns `agents/fabric-migration-orchestrator/agent.md`.
- The `spark_compute`-stripping micro-question stays open (resolve at the manual deploy round-trip).

---

## Slice 4 — Python silver builder path ✅ DONE 2026-06-08

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

### Outcome note (implementation pass — NOT marked Done; main agent to confirm)

**Status:** implemented + all 8 plan tests green (test 8 ran as a real assertion, see below). Left for the main agent to mark Done after the integration join.

**Files created:**
- NEW `tests/test_silver_python.py` — the 8 plan tests + 1 bonus `agent.md` engine-awareness guard. Standalone runner (`_check`/`main()`), no pytest.
- NEW `tests/fixtures/golden/python/nb_silver_customers.ipynb` — hand-authored representative Python silver golden (jupyter kernel, `lh_silver` binding, `%run utilities/nb_utils_config` → `read_bronze("customers")` → polars rename/cast/decode/null/dedup/filter → `add_silver_metadata` → `write_deltalake(table_path(...), mode="overwrite", schema_mode="overwrite")` → `validate_row_count`).
- NEW `tests/fixtures/golden/pyspark/nb_silver_customers.ipynb` — representative PySpark silver golden for the test-7 regression (none existed before; only a bronze pyspark golden did). Distinct filename from bronze.

**Files edited:**
- `agents/fabric-silver-builder/agent.md` — added an **"Engine Awareness (READ FIRST)"** section + a full **"Python Engine Path (engine=python)"** section (Python-kernel metadata block; polars cell structure; bronze-only read with the polars/mount forbidden list; polars transform idioms + type map per research §4; `add_silver_metadata` swap; `write_deltalake(..., mode="overwrite", schema_mode="overwrite")` write via `table_path()`; delta-rs `validate_row_count`; no-Spark-leakage rules). **PySpark instructions left byte-identical** — the new content is additive, inserted before "## Development Workflow"; description broadened to "PySpark or Python engine".

**The 8 plan tests (all green):** 1 valid jupyter-kernel `.ipynb` + `lh_silver` binding ✅ · 2 read_bronze-only / no external reads (`pl.read_csv/read_parquet/read_ndjson/scan_*`, **`pl.read_delta` directly**, `abfss://`/`wasbs://`/`Files/`, `os.walk`, `glob.glob`, `pd.read_*` all banned) ✅ · 3 `mode="overwrite"` + `schema_mode="overwrite"` (and NOT append) ✅ · 4 metadata swap (`add_silver_metadata`, no `add_bronze_metadata`) ✅ · 5 no Spark idioms (`spark.`/`F.`/pyspark/`saveAsTable`/`withColumnRenamed`) ✅ · 6 passes the live `validate-fabric-structure.py` hook (read_bronze-only body satisfies the silver forbidden list — no Slice-6 change needed) ✅ · 7 PySpark silver golden diff-clean (synapse_pyspark kernel, `saveAsTable`/overwrite, no polars leakage) ✅ · 8 bronze→silver round-trip ✅ **(ran as a real assertion, not a skip — the Slice-3 parallel agent's `tests/fixtures/golden/python/nb_bronze_customers.ipynb` already existed; both notebooks use source `customers`, so `read_bronze("customers")` resolves the `bronze_customers` the bronze golden writes).** Tolerant-skip path is retained in the test for the case where the bronze golden is absent.

**Regressions green:** `preshipment_audit.py`, `test_engine_toggle.py`, `test_python_reference_set.py`, `test_risk_catalog.py` — all PASS.

**Default decisions (documented here + inline in test/golden):**
- **Golden-testing approach:** the silver builder is LLM-authored (not script-reproducible), so the tests assert **structural properties** of a hand-authored representative golden (mirrors the Slice-2/Slice-3 builder-golden convention), plus an `agent.md` instruction-contract guard. No attempt to diff exact builder output.
- **`pl.read_delta` banned in the silver body** (not just external paths): `read_bronze` itself wraps `pl.read_delta(table_path(...))` inside `nb_utils_config`. Allowing a bare `pl.read_delta` in the silver body would let it read an arbitrary delta path and bypass the bronze-only contract — so the body must go through `read_bronze` exclusively. This is stricter than research §4's table (which lists `pl.read_delta` as the generic delta read) and is the security-correct reading of the silver contract.
- **Silver write idiom emitted:** `write_deltalake(table_path(TABLE_NAME), df_silver.to_arrow(), mode="overwrite", schema_mode="overwrite")` — the polars/delta-rs analogue of `mode("overwrite") + overwriteSchema=true + saveAsTable`. Path always via `table_path()` (never hard-coded `Tables/...`), so the "Unidentified table" registration gotcha (research §5) stays handled in one place.
- **Dedup idiom emitted:** `df.sort("_load_timestamp", descending=True).unique(subset=[...], keep="first", maintain_order=True)` (research §4 Window→unique mapping). The golden dedups BEFORE `add_silver_metadata` so `_load_timestamp` is still present at sort time.
- **PySpark silver golden authored fresh** (test 7) because only a bronze pyspark golden existed; it uses the exact idioms from this agent's PySpark section (Window dedup, `fillna`, `saveAsTable` overwrite + `overwriteSchema`) so it doubles as a baseline if the PySpark path is ever touched.

**Deferred:** the **manual Fabric** runtime round-trip (deploy the golden, confirm it registers as a Python notebook + the `table_path()` write actually registers `silver_customers` — research §5's highest-risk runtime behavior) stays manual, exercised when Fabric access is available. Orchestrator **Stage 9 prompt thread** of `engine` into the silver-builder call is OUT of this slice's territory (the main agent owns `fabric-migration-orchestrator/agent.md`) — the agent is now engine-ready to receive it.

---

## Slice 5 — M→Python converter ✅ DONE 2026-06-08

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

### Outcome note (implementation pass — NOT marked Done; main agent to confirm)

**Status:** implemented + all 6 plan tests green. Left for the main agent to mark Done.

**Files created/edited:**
- NEW `skills/m-to-pyspark-converter/scripts/polars_generator.py` — `PolarsGenerator`, mirrors `PySparkGenerator`'s structure, shares `MParser`.
- `skills/m-to-pyspark-converter/scripts/function_map.py` — added `M_TO_POLARS_TYPES`, `M_TO_POLARS_JOIN`, `M_TO_POLARS_AGG`, `M_TO_POLARS_TEXT` + resolvers `get_polars_type`/`get_polars_join_type`/`get_polars_agg`.
- `skills/m-to-pyspark-converter/scripts/convert_m_to_pyspark.py` — `--target python|pyspark` (default `pyspark`); `TARGETS` map + `get_generator()`; unknown target → `argparser.error` (non-zero exit).
- `skills/m-to-pyspark-converter/SKILL.md` — description broadened to both targets (skill **name unchanged** for compatibility); added polars mapping reference + `--target python` usage.
- NEW `tests/test_converter_python_target.py` — the 6 plan tests + 1 bonus security parity test. All green.

**Tests:** 1 `test_target_pyspark_unchanged` ✅ · 2 `test_target_python_table_ops` ✅ · 3 `test_target_python_type_map` ✅ · 4 `test_target_python_expressions` ✅ · 5 `test_target_python_unknown_emits_todo` ✅ · 6 `test_cli_rejects_unknown_target` ✅. Regressions green: `preshipment_audit`, `test_engine_toggle`, `test_risk_catalog`, `test_report_patterns_parser`.

**Default decisions made (research §4 ambiguities), documented inline in code:**
- **No existing converter `.pq`/regression fixtures existed** (git-log "regression tests" = `test_risk_catalog.py`, not converter). Used inline M-string fixtures inside the new test — no separate fixtures dir needed.
- **`Table.Combine` → `pl.concat([...], how="diagonal_relaxed")`** (research §4 gave only "concat"). `diagonal_relaxed` is the union-by-name-with-schema-superset analogue of Spark `unionByName`; chosen so mismatched/extra columns don't crash.
- **`JoinKind.RightAnti` → `how="anti"` + review TODO.** polars has no right-anti `how`; "anti" is left-anti. Emits a TODO telling the user to swap operands if true right-anti is needed.
- **Sort:** all-descending → `descending=True`; all-ascending → bare; mixed → `descending=[...]` list.
- **`Table.TransformColumnTypes` decimal/`Currency.Type`** uses `pl.Decimal(19, 4)` / `pl.Decimal(38, 18)` per the §4 addendum.
- **`Table.Buffer` → no-op** (polars eager; emits a comment, keeps `df` unchanged).
- **Unknown M op → same `# TODO` block** the PySpark emitter uses (parity; never crashes).
- **Write idiom** = `write_deltalake(table_path(target_table), df.to_arrow(), mode="overwrite", schema_mode="overwrite")`; reads via `pl.read_delta(table_path(...))`. The `table_path()` resolver is expected from the Slice 2 Python utilities notebook (not this slice's responsibility).
- **Security:** source connection strings (server/db) appear **only in comments**, never executable code — verified by the bonus test.

**Deferred / not in this slice:** the actual `table_path()` helper + Python `nb_utils_config` (Slice 2); builder integration calling `--target python` (Slice 3/4). The polars emitter currently outputs `.py` source text via `--m-code/--m-file` exactly like the PySpark emitter; wrapping into `.ipynb` is the builder's job, unchanged here.

---

## Slice 6 — Engine-aware gates (hook + validator) ✅ DONE 2026-06-08

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

### Outcome note (implementation pass — NOT marked Done; main agent to confirm)

**Status:** implemented + all 8 Slice-6 tests green (RED→GREEN verified). Regressions green. Left for the main agent to mark Done.

**Files created:**
- NEW `tests/test_engine_aware_gates.py` — the 8 Slice-6 tests. Standalone runner (`_check`/`main()`, no pytest). Notebook fixtures are built **programmatically in-test** (a `_make_nb(engine, code_cells)` helper emits minimal valid `.ipynb` with the correct PySpark/Python metadata block + lakehouse binding), so no fixture files needed under `tests/fixtures/gates/` — the dir is reserved but unused this pass (documented default; avoids shipping near-duplicate static fixtures).

**Files edited:**
- `hooks/validate-fabric-structure.py` — made **engine-aware**. Added `_detect_engine()` (reads metadata), `_code_source()` (scans CODE cells only), split the silver forbidden set into `_SILVER_FORBIDDEN_PYSPARK` (byte-identical to the old list) + `_SILVER_FORBIDDEN_PYTHON` (polars/mount/pandas external reads + `pl.read_delta`/`DeltaTable` in body + `os.walk`/`glob.glob` + abfss/wasbs/Files), added `_validate_engine_leak()` with `_SPARK_IN_PYTHON_FORBIDDEN` + `_PYTHON_IN_PYSPARK_FORBIDDEN`, and wired all three into `main()`. The silver branch still **requires** a `read_bronze(` call on both engines (bronze-only contract preserved, never weakened). `.py`-in-`3 - Notebooks/` block + `_emit_defer()`-on-error/non-notebook behaviour unchanged.
- `agents/fabric-pipeline-validator/agent.md` — added **Step 0 (detect engine per notebook)**, engine-aware **Check 1.1** (positively assert `microsoft.language_group == "jupyter_python"` + `kernel_info.name == "jupyter"` for Python; `synapse_pyspark` for PySpark — a Python notebook missing the discriminator → FAIL), engine-split **Check 1.2** (PySpark column unchanged; Python column = `write_deltalake` append+merge / overwrite+overwrite via `table_path()`, metadata cols, leak guards), a **delta-rs/duckdb row-count** rule (never a Spark `.count()` on the Python path), a Step-2.2 engine-appropriate-count note, and updated the **Severity FAIL** list (kernel-discriminator-missing, cross-engine leak, engine-mismatch). PySpark contract wording byte-preserved.
- `tests/preshipment_audit.py` — **not changed.** The existing `notebook_extension` (N17) gate that blocks `.py` notebook prescriptions is idiom-agnostic and already covers both engines; the hook keeps blocking `.py` in `3 - Notebooks/` for both engines. No test drove a preshipment change, so none was made (avoids gold-plating). All 7 existing gates stay green.

**The 8 tests (all green):** 1 `test_hook_pyspark_silver_unchanged` (clean allowed; external-read + missing-read_bronze still blocked) ✅ · 2 `test_hook_python_silver_external_read_blocked` (`pl.read_csv` / `os.walk` / `pl.read_delta` → block) ✅ · 3 `test_hook_python_silver_read_bronze_ok` ✅ · 4 `test_hook_python_bronze_external_read_ok` (bronze `glob`/`pl.read_csv` of `Files/` allowed) ✅ · 5 `test_validator_asserts_python_kernel_group` ✅ · 6 `test_validator_python_write_idiom` (bronze append / silver overwrite / delta-rs row-count, scoped to the `engine=python` section) ✅ · 7 `test_cross_engine_leak_spark_in_python` (`spark.read`/`F.col` in jupyter → block) ✅ · 8 `test_cross_engine_leak_python_in_pyspark` (`write_deltalake`/`import polars` in synapse_pyspark → block) ✅.

**Regressions green:** `test_bronze_python.py` (incl. test-6 live-hook feeder), `test_silver_python.py` (incl. test-6 live-hook feeder), `preshipment_audit.py` (7/7), `test_engine_toggle.py` (6/6). All four real goldens (pyspark+python bronze+silver) DEFER through the live hook — PySpark byte-behaviour unchanged.

**Default decisions made (documented inline):**
- **Engine detection from metadata:** `metadata.microsoft.language_group == "jupyter_python"` (or `kernel_info.name`/`kernelspec.name == "jupyter"`) ⇒ Python; everything else ⇒ PySpark branch. This guarantees any notebook **without** the Python discriminator takes the unchanged `synapse_pyspark` path (no byte-behaviour drift). On an Edit fragment that isn't full JSON, falls back to a `jupyter_python` substring probe.
- **Idiom scans run on CODE CELLS only** (`_code_source`), NOT the whole JSON — because Fabric's real Python metadata embeds a residual `spark_compute` block (`spark.synapse.nbs.session.timeout`) that would false-positive the `\bspark\.` leak pattern. Verified against the real python bronze golden (which carries that block) — it defers.
- **Cross-engine leak severity = BLOCK in BOTH directions** (chosen over WARN). A leaked idiom ships a non-runnable notebook (Spark idiom → no Spark session single-node; delta-rs idiom → wrong kernel), so failing loud at write-time beats a warning the orchestrator may not surface. Documented in the hook docstring + the test header.
- **`pl.read_delta` / `DeltaTable(` banned in the silver BODY** (not just external paths) — `read_bronze` itself wraps `pl.read_delta(table_path(...))` inside the utils notebook; a bare call in the silver body would bypass the bronze-only contract. Matches the Slice-4 stricter reading.
- **`tests/fixtures/gates/` reserved but unused** — fixtures are generated in-test for self-containment + zero fake-GUID/secret risk; the static-fixture dir stays available if a future case needs a captured real notebook.

**Deferred:** none functionally. The manual-Fabric runtime checks (deploy round-trip, live row counts) remain the validator's runtime mode, exercised when Fabric access is available (epic anti-scope: no notebook execution in CI). Orchestrator does not need a change for Slice 6 (the hook + validator are invoked as today).

---

## Slice 7 — Risk-catalog addendum + docs ✅ DONE 2026-06-08

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

### Outcome note (implementation pass 2026-06-08 — NOT marked Done; main agent to confirm at the join)

**Status:** implemented + all 3 Slice-7 tests green; `test_risk_catalog.py` stays green (verified after every catalog edit). Left for the main agent to mark Done after the integration join.

**Files created:**
- NEW `tests/test_catalog_engine_addendum.py` — the 3 Slice-7 tests (standalone `_check`/`main()` runner, no pytest).

**Files edited:**
- `reference/m-conversion-risk-catalog.md` — added a `**Python:**` applicability line to **all 30** RISK-NN sections; added an **"Engine applicability"** legend section (after "How to use this catalog") defining the four markers; added a **"Spark-only optimizations (N-A on the Python engine)"** subsection under the severity matrix (V-Order / NEE / Vegas cache); added a `**Python:**` bullet to the "How to use" list.
- `README.md` — added a **"Python engine limitations"** subsection (single-node memory; no env vars / Environment item / library item; some Delta features unsupported incl. V-Order/NEE/Vegas N-A) under the existing decision matrix; **rewrote the Slice-1 interim status paragraph** (see exact wording below).
- `_Documentation/pipeline-workflow.md` — **existed**; added a **"Notebook engine toggle"** section (decision matrix + Python limitations + engine-aware-gate note + status line) after the Invocation section; bumped Last-updated to 2026-06-08.

**The 3 Slice-7 tests (all green):** 1 `test_catalog_parses_with_engine_column` (re-asserts the `test_risk_catalog.py` structural rules — 30 headings, Detection each, mitigation each, header count) ✅ · 2 `test_every_risk_has_engine_note` (every RISK-NN has a `**Python:**` line carrying one of ease/worsen/N-A/unchanged) ✅ · 3 `test_readme_documents_toggle` (README names `notebook_engine`, both values, the decision matrix, AND the three Python limitations) ✅. RED→GREEN verified (31 fails before edits: 30 catalog notes + the README Delta-features limitation). Regressions green: `test_risk_catalog.py`, `test_engine_toggle.py`.

**Decisions made (documented inline, per the "resolve ambiguity with a sensible default" rule):**
- **Engine-note format chosen:** a single `**Python:** <marker> — <rationale>` line per RISK section, where `<marker>` ∈ {`ease`, `worsen`, `N-A`, `unchanged`}. Chosen over an added table column because the catalog is **prose-with-fenced-blocks, not tabular** — a column would have required restructuring all 30 entries and risked breaking the `test_risk_catalog.py` mitigation regex. A per-section line is additive, leaves every existing fence/table/callout intact, and reads naturally next to each mitigation. The legend section documents the four markers.
- **Per-risk classification** (advisory, does not change analyst-reported severity): **ease** (8) — RISK-02, 04, 05, 06, 09, 13, 18, 20, 21, 27, 28, 29 (distributed-execution hazard disappears on single node, or polars has a first-class op); **worsen** (2) — RISK-03 (Excel, no Spark fan-out), RISK-10 (joins materialize in 16 GB RAM); **unchanged** (rest) — connector auth, regex/string ops, OneLake-shortcut admin, dict/conditional ops. **N-A** is used for the Spark-only optimizations (V-Order/NEE/Vegas) which are not their own RISK-NN — called out in the dedicated subsection + the README rather than forced onto an unrelated risk.
- **MEMORY.md:** **no pointer added.** There is no repo-tracked `MEMORY.md` (the auto-memory MEMORY.md lives in the Claude projects cache, outside the repo), and the one durable engine gotcha — the "Unidentified table" registration handling — is already fully documented in `reference/python-delta-patterns.md` (Slice 2) and now cross-referenced from the catalog legend + pipeline-workflow doc. Creating a new tracked MEMORY.md just to point at existing docs would violate the thin-MEMORY / don't-create-unnecessary-files rules.

**Exact README interim-status rewrite** (replaced the Slice-1 "Python notebook generation is not yet wired … Leave the default pyspark for now" paragraph; does NOT overclaim production-readiness):
> **Status:** the toggle is plumbed end-to-end (config → `--engine` flag → `project-config.yml` → Section 0), and the **Python builders + the M→Python converter now emit Python-kernel notebooks** — `engine=python` produces `jupyter`-kernel bronze + silver `.ipynb` with polars/delta-rs idioms (`microsoft.language_group: jupyter_python`, lakehouse binding, `write_deltalake` writes via the `table_path()` resolver). What remains is the **live Fabric round-trip validation** (deploy the notebooks, confirm they register as Python notebooks and that `table_path()` writes register the Delta tables) — that step is **manual and offline for now**, exercised when Fabric access is available. Treat the Python engine as **functionally complete but not yet round-trip-verified against a live workspace**; `pyspark` remains the default and the regression baseline.

**Deferred:** nothing in Slice 7 scope. The live Fabric round-trip validation referenced in the new README/workflow status is the same manual check carried by Slices 3/4 (out of this docs slice). Did NOT run `tests/preshipment_audit.py` (parallel Slice-6 agent may be mid-edit — main agent runs the full suite at the join).

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

---

## Integration pass — RAN 2026-06-08 (offline, real builders on bundled samples)

Drove the real chain on `Sample Education Data` with `engine=python`: scaffold (`--engine python`) → `dataflow-gen1-extractor` (5 queries) → `m-to-pyspark-converter --target python` → **real** `fabric-bronze-builder` + `fabric-silver-builder` subagents → live `validate-fabric-structure.py` hook. Replaces the integration gate that the 6→7 parallel run had skipped.

**What works (verified, not self-reported):** end-to-end produced a valid `nb_bronze_schools.ipynb` + `nb_silver_schools.ipynb` — jupyter kernel + `jupyter_python`, correct lakehouse bindings, bronze `write_deltalake(..., mode=append, schema_mode="merge")`, silver `read_bronze`-only + `overwrite`, `%run` utilities, syntax-clean (every code cell `compile()`s). The engine-aware hook was proven live on real output: **allows** the clean silver, **blocks** an injected `pl.read_csv("Files/...")`.

**Defects the integration surfaced (unit tests missed — they used clean single-level inline M):**
1. **Converter nested `if/then/else` → invalid Python.** `polars_generator` only converts the first condition; the remainder is dumped into `pl.lit("...")` with **unescaped quotes** (syntax error). The LLM builder corrected it into a proper `pl.when().then()...otherwise()` chain, but the raw converter output is broken. **Fix `polars_generator` to recurse on nested ifs.** (PySpark target likely has the same gap — check.)
2. **Converter mislabels layer + hardcodes `overwrite`.** Output is titled `nb_bronze_*` yet emits `mode="overwrite"` and uses `table_path()` without defining/importing it. Builder overrides correctly; converter snippet is misleading standalone.
3. **Converter `--output FILE` mishandles the path** (treats it as a dir → writes `<file>\nb_*.py`). Minor CLI ergonomics.
4. **Gate brittleness vs real output.** Slice-6 validator wording + the bronze golden assert the literal `mode="append"`; the real builder emitted `mode=load_mode` (a variable set to `"append"`). Functionally correct but the literal-string assertion would miss it. Loosen the gate/validator to accept a variable, or instruct builders to emit the literal.
5. **Builder metadata inconsistency.** bronze wrote `kernelspec.name="jupyter"`, silver wrote `kernelspec.name="python3"` (both carry the correct `jupyter_python` discriminator). Align the two builders on one metadata shell (mirror the Slice-0 confirmed export).
6. **Architecture (not engine-specific):** a single M query that ingests + joins gets the **join placed in the bronze notebook** (`bronze_schools` reads `bronze_ofsted_rating` → intra-bronze ordering dependency). Pre-existing pipeline behaviour; revisit whether joins belong in silver.

**Still deferred:** live Fabric deploy/run round-trip (needs a workspace).
