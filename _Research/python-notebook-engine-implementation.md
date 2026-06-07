# Research: Adding a Python-notebook engine (PySpark ⇄ Python toggle)

**Date:** 2026-06-07
**Author:** research pass for the `fabric-dataflow-migration-toolkit` plugin
**Driver article:** [Choosing Between Python and PySpark Notebooks in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-engineering/fabric-notebook-selection-guide)
**Goal:** Let a migration emit **100 % Python notebooks** (single-node, polars/duckdb/delta-rs) instead of **100 % PySpark notebooks**, selectable by a single toggle at the start of the run, for low-volume solutions.

> Scope note: this is a **research document only**. No plugin code is changed here. The implementation plan / slices at the end are proposals to review before any build.

---

## 1. Executive summary

The plugin today generates **PySpark `.ipynb`** notebooks end-to-end: the two builder agents (`fabric-bronze-builder`, `fabric-silver-builder`), the `m-to-pyspark-converter` skill, the three reference guides (`pyspark-style-guide.md`, `notebook-template.md`, `delta-lake-patterns.md`), the structure hook, and the validator all assume Spark (`spark.read`, `F.*`, `saveAsTable`, `synapse_pyspark` kernel).

Fabric now ships a **pure-Python notebook** runtime: a single-node 2-vCore/16 GB container running a **Python 3.10/3.11 kernel** (not Spark), with **polars, duckdb, delta-rs (`deltalake`), pandas, pyarrow, and `notebookutils`** pre-installed. It reads and writes Delta tables to the same lakehouse, costs less, and starts faster — but caps out around **single-node memory (~1 GB comfortable, multi-GB risky)**.

Adding the toggle is **feasible and self-contained**, but it is **not a trivial flag** — it requires a parallel code-generation path because almost every line of generated Spark code has a different Python idiom. The work breaks into five buckets:

1. **A toggle** (`notebook_engine: pyspark | python`) surfaced at Stage 1 and threaded through the orchestrator to every builder.
2. **A Python reference set** mirroring the three PySpark guides (style, template, delta patterns) plus a Python utilities notebook (`read_bronze`, metadata helpers, table-path resolver).
3. **A Python code-gen path in the builders** (parameterize the existing agents by `engine`, reading the engine-appropriate reference set — recommended over forking two new agents).
4. **An M→Python converter** (polars target) — a sibling to `m-to-pyspark-converter`, or a `--target python` flag on it.
5. **Engine-aware gates** — the structure hook and `fabric-pipeline-validator` currently hard-assert Spark idioms; they must branch on engine.

**Single biggest de-risk item:** the exact `.ipynb` **kernel metadata** for a Fabric Python notebook is not documented as JSON and must be confirmed empirically (export a real Python notebook with `fab`). If the deployed notebook carries the wrong kernel metadata, Fabric runs it as the wrong type. See §8.

---

## 2. The decision: when Python, when PySpark (from the MS article)

| Signal | Python notebook | PySpark notebook |
|---|---|---|
| Data size | Small–medium, **fits in memory** (article: "up to 1 GB" for quick transforms) | **10 GB+**, exceeds single-node memory |
| Compute | Single-node **2 vCore / 16 GB** (min 2 vCores) | Spark cluster, **min 4 vCores**, autoscale |
| Startup | ~5 s (starter pool) → up to 3 min (on-demand) | ~5 s → several minutes |
| Cost | Lower; ad-hoc / scheduled micro-jobs | Higher; scalable long-running ETL |
| Libraries | pre-installed **DuckDB + Polars**; pip-installable | full **MLlib, Spark SQL, Spark Streaming** |
| Delta Lake | **delta-rs + duckdb** pre-installed; *some Delta features unsupported* | native, fully optimized (NEE, VORDER, Vegas cache) |
| Concurrency | manual FIFO per notebook | system-managed FAIR/FIFO |
| Production | **no env vars, no Environment item, no library item** | env vars, Environment item, item-based libs |

**Implication for the toggle design.** The article frames this as a **per-workload** choice that **evolves** (start Python, scale to PySpark). The user's requirement is a **single global toggle per migration** ("100 % pyspark or python") — simpler and the right v1. We should **honor the global toggle as the user's authoritative decision**, with **no data-driven advisory** (see the correction below).

> **Correction (verified 2026-06-07): the migration pipeline has no source-volume signal at planning time.** The orchestrator's 13 stages never invoke the `data-profiler` skill (grep-confirmed: zero calls in the orchestrator or any agent). The migration works purely from **dataflow definitions** — exported Gen1 JSON parsed into `.pq` M-query files — and never connects to the underlying sources (the SQL Server / SharePoint / Web API behind the dataflow). That offline-by-design property is *why* `--sample --dry-run` works with no credentials. The `data-profiler` is a **shared skill inherited from the plugin family's dbt lineage**; it profiles `localhost` SQL Server or **local** CSVs in `2 - Source Files/` — but in a dataflow migration that folder holds JSON/`.pq` files, not source extracts, and `profile_data.py` does **not** compute byte/MB size anyway (only `total_rows` via `COUNT(*)`/`len`, plus column stats). The builders' "check `1 - Documentation/data-profiles/` if available" line is optional/aspirational and is normally empty in a migration. **Therefore the engine choice is a pure user decision** — there is no row count or size to base an OOM warning on without a scope-expanding new "connect to sources and size them" stage. See §7.4 for the (de-scoped) advisory options.

---

## 3. Fabric Python notebook — technical reference

Source: [Use Python experience on Notebook](https://learn.microsoft.com/en-us/fabric/data-engineering/using-python-experience-on-notebook).

### 3.1 Runtime & kernel
- Kernels: **Python 3.10** and **Python 3.11** (default 3.11). Switchable in UI. **No Spark session** — there is no `spark` object, no `pyspark.sql.functions`, no `delta.tables.DeltaTable`.
- Single node, **2 vCore / 16 GB** default. Scale via `%%configure` (see 3.5).
- iPython features: magics, iPyWidgets, `display()` rich table/chart all work.
- Restart kernel: `notebookutils.session.restartPython()` (not `sys.exit(0)`).

### 3.2 Pre-installed libraries
**polars, duckdb, pandas, pyarrow, scikit-learn, deltalake (delta-rs), notebookutils, semantic-link, mlflow, matplotlib/seaborn/plotly.**
OOM guidance from the doc: *"If you encounter OOM when loading large volume of data, try using DuckDB, Polars or PyArrow dataframe instead of pandas."* → our generated Python code should prefer **polars / duckdb**, not pandas, as the default engine.

### 3.3 Lakehouse I/O (the core of the port)
- Default lakehouse mounts at **`/lakehouse/default/`** → tables under **`/lakehouse/default/Tables/`**, files under **`/lakehouse/default/Files/`**.
- **Read** a delta table: `pl.read_delta("/lakehouse/default/Tables/<name>")` / `pl.scan_delta(...)` (lazy), or `duckdb.sql("SELECT * FROM delta_scan('...')")`, or `deltalake.DeltaTable(path).to_pyarrow_table()`.
- **Write** a delta table: `deltalake.write_deltalake(path, arrow_or_df, mode=...)` or polars `df.write_delta(path, mode=...)`.
- UI affordances ("drag & drop", "Load data", "Browse code snippet → Write data to delta table") confirm these are the blessed patterns.

### 3.4 NotebookUtils (available in Python notebooks)
- `notebookutils.fs`, `notebookutils.notebook.run()/.runMultiple()`, `notebookutils.runtime.context` (run id for `_load_id`), `notebookutils.credentials.getSecret(...)`, `notebookutils.session.restartPython()`.
- **`notebookutils.data.connect_to_artifact(...)`** (preview, **Python-notebook only**): opens an ODBC/T-SQL connection to a Lakehouse/Warehouse/SQL endpoint and returns a `.query("SELECT …")` → DataFrame. Useful for SQL-source bronze ingestion without Spark JDBC.

### 3.5 `%%configure` (must be the first cell)
```json
%%configure -f
{
    "vCores": 4,                       // [4, 8, 16, 32, 64]; matched memory auto-allocated
    "defaultLakehouse": { "name": "<lakehouse>", "id": "<id>", "workspaceId": "<wsid>" },
    "mountPoints": [ { "mountPoint": "/mnt", "source": "abfss://…" } ]
}
```
This is the Python equivalent of the PySpark `%%configure` cell already in `notebook-template.md`. Note default is **2 vCores**; `%%configure` minimum bump is **4**.

### 3.6 `%run` limitation (affects the silver utilities pattern)
> "Currently, `%run` only supports referencing **notebook items** on Python notebook, **not code modules (.py)** from the resources folder."

The silver builder today emits `%run utilities/nb_utils_config` as **cell 0**. That works **only if** `nb_utils_config` is a **notebook item** (it is, in the scaffold). So the `%run`-based `read_bronze()` / `add_silver_metadata()` helper pattern is **portable** to Python — provided the utilities notebook itself is regenerated in Python form. Good news: this keeps forbidden tokens (paths, `abfss://`) **inside the helper notebook**, out of the silver notebook body, which keeps the structure hook happy (see §6).

### 3.7 Known limitations to bake into generated code / docs
- **No Environment item, no env vars, no library item** → all deps via `%pip install` inline if not pre-installed.
- Session start may take **up to 3 min** if it misses the live pool.
- "Some Delta Lake features may not be fully supported" (delta-rs ≠ full Delta spec). Notably **VORDER / NEE / Vegas cache are Spark-only** — the gold-layer VORDER guidance in `delta-lake-patterns.md` has **no Python equivalent**; Python tables can be V-ORDER-optimized later by a Spark job or by the SQL endpoint's background optimization.

---

## 4. PySpark → Python translation reference (the meat)

This is the mapping the Python builders + converter must implement. Default engine = **polars** (duckdb for set-based SQL-style transforms; delta-rs for the Delta write/merge).

| Concern | PySpark (today) | Python (proposed) |
|---|---|---|
| Imports | `from pyspark.sql import functions as F` | `import polars as pl` / `import duckdb` / `from deltalake import write_deltalake, DeltaTable` |
| Read CSV (bronze) | `spark.read.format("csv").option("header",true)…` | `pl.read_csv(path)` (or `duckdb.read_csv`) |
| Read parquet/json | `spark.read.format("parquet"/"json")` | `pl.read_parquet(path)` / `pl.read_ndjson(path)` |
| Read delta table | `spark.read.table("bronze_x")` | `pl.read_delta("/lakehouse/default/Tables/bronze_x")` |
| Read SQL source | `spark.read.jdbc(...)` | `notebookutils.data.connect_to_artifact(...).query(...)` or `duckdb`/`connectorx` |
| Write delta (append + schema evo) | `.write.format("delta").mode("append").option("mergeSchema","true").saveAsTable("bronze_x")` | `write_deltalake(path, df.to_arrow(), mode="append", schema_mode="merge")` |
| Write delta (overwrite + schema) | `.mode("overwrite").option("overwriteSchema","true")` | `write_deltalake(path, arrow, mode="overwrite", schema_mode="overwrite")` |
| MERGE / upsert | `DeltaTable.forName(...).merge(...).whenMatched…` | `DeltaTable(path).merge(source, predicate, ...).when_matched_update_all().when_not_matched_insert_all().execute()` (delta-rs `TableMerger`) |
| Add col | `df.withColumn("c", F.…)` | `df.with_columns(pl.lit(...).alias("c"))` |
| Rename | `df.withColumnRenamed("a","b")` | `df.rename({"a": "b"})` |
| Cast | `F.col("x").cast("decimal(18,2)")` | `pl.col("x").cast(pl.Decimal(18,2))` |
| Filter | `df.filter(F.col("x") > 0)` | `df.filter(pl.col("x") > 0)` |
| Dedup (latest) | `Window.partitionBy(…).orderBy(…desc())` + `row_number()==1` | `df.sort("_load_ts", descending=True).unique(subset=[...], keep="first")` |
| Decode/case | `F.when(...).otherwise(...)` | `pl.when(...).then(...).otherwise(...)` |
| Unpivot | `selectExpr("stack(...)")` / `df.unpivot` | `df.unpivot(index=[...], on=[...], variable_name=..., value_name=...)` |
| Join | `df.join(r, on, "left")` | `df.join(r, on=..., how="left")` |
| `_load_timestamp` | `F.current_timestamp()` | `datetime.now(timezone.utc)` as a literal column |
| `_source_file` | `F.input_file_name()` | source path literal (no per-row equivalent single-node) |
| `_load_id` | `notebookutils.runtime.context.get("currentRunId","manual")` | **same** — `notebookutils.runtime.context` works in Python |
| Row count validate | `spark.table("x").count()` | `DeltaTable(path).to_pyarrow_dataset().count_rows()` or `pl.read_delta(path).height` |
| VORDER / optimizeWrite | `spark.conf.set("spark.sql.parquet.vorder.enabled", …)` | **N/A** (Spark-only) — drop, or defer to a later Spark optimize |

**Type mapping addendum** (extend the converter's existing M-type table with a polars column): `type text`→`pl.Utf8`, `type number`→`pl.Float64`, `Int64.Type`→`pl.Int64`, `type date`→`pl.Date`, `type datetime`→`pl.Datetime`, `type logical`→`pl.Boolean`, `Decimal.Type`→`pl.Decimal`, `Currency.Type`→`pl.Decimal(19,4)`.

---

## 5. The "Unidentified table" registration gotcha (must-handle)

Source: [Fabric community thread](https://community.fabric.microsoft.com/t5/Data-Engineering/write-deltalake-with-Python-Notebook-is-creating-an-quot/m-p/4407839).

When `write_deltalake` / `polars.write_delta` writes Delta files to a managed path, the files are valid and queryable, but the **lakehouse catalog may not register the logical table** — it shows under an **"Unidentified"** folder. Causes & fixes:

1. **Schema-enabled lakehouse needs the schema in the path.** Write to `…/Tables/dbo/<table>`, not `…/Tables/<table>`. Omitting `dbo` lands it in "unidentified."
2. **Prefer the full ABFSS path** for deterministic registration:
   `abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>.Lakehouse/Tables/dbo/<table>`
3. **Or register with DDL after write:** `CREATE TABLE <t> USING DELTA LOCATION '/lakehouse/.../Tables/.../<t>'`.
4. Auto-registration happens **eventually** but not immediately — bad for a pipeline that writes bronze then immediately reads it in silver.

**Design consequence.** The Python utilities notebook must own a **`table_path(name)` resolver** that knows whether the target lakehouse is **schema-enabled** (`Tables/dbo/<name>`) or not (`Tables/<name>`), so builders never hard-code paths and the registration gotcha is handled in one place. The scaffold's `project-config.yml` should record `schema_enabled: true|false` per lakehouse. This is the **highest-risk runtime behavior** of the Python path and deserves an explicit integration test (write bronze → read it back in silver in the same run).

---

## 6. Gap analysis — every component that must change

| # | Component | Today (PySpark) | Change for Python engine | Effort |
|---|---|---|---|---|
| 1 | `.claude-plugin/plugin.json` userConfig | no engine setting | add `notebook_engine` (`pyspark`\|`python`, default `pyspark`) | S |
| 2 | Orchestrator agent | no engine concept | Stage 1 ask/read engine; write to Section 0; thread `engine` into every builder prompt; Stage 7 approval shows engine; (optional) profiling advisory | M |
| 3 | `fabric-bronze-builder` | Spark-only template & rules | `engine`-aware: read Python reference set, emit polars+delta-rs cells, Python metadata cols, `write_deltalake(mode="append", schema_mode="merge")` | L |
| 4 | `fabric-silver-builder` | Spark-only, `read_bronze()` via `%run` | `engine`-aware: polars transforms, `write_deltalake(mode="overwrite", schema_mode="overwrite")`, keep `%run` utilities (notebook item) | L |
| 5 | `m-to-pyspark-converter` skill | M→PySpark only | sibling `m-to-python-converter` **or** `--target python` flag; polars mapping table + type map | L |
| 6 | `reference/pyspark-style-guide.md` | — | new `reference/python-style-guide.md` (polars idioms, no-`F.`, OOM-safe defaults) | M |
| 7 | `reference/notebook-template.md` | PySpark cell templates | add Python bronze/silver/orchestration templates (incl. `%%configure` vCores, Python kernel metadata) | M |
| 8 | `reference/delta-lake-patterns.md` | Spark Delta API | new `reference/python-delta-patterns.md` (write_deltalake, delta-rs merge, table_path resolver, registration gotcha) | M |
| 9 | Utilities notebook (`nb_utils_config`) | PySpark helpers | Python version: `read_bronze()`, `add_bronze_metadata()`, `add_silver_metadata()`, `silver_table()`, `table_path()`, `validate_row_count()` in polars/delta-rs | M |
| 10 | `hooks/validate-fabric-structure.py` | bans `spark.read.*`, `pd.read_*`, `abfss://`, `Files/` in silver; checks lakehouse binding | **engine-aware**: for Python, the forbidden set differs (ban `pl.read_csv`/`read_parquet`/`scan_delta` of external paths in silver; still require `read_bronze`). Does **not** currently check kernel name — fine. | M |
| 11 | `fabric-pipeline-validator` | asserts 6-cell Spark structure, `mergeSchema`, `saveAsTable`, `spark.read` bans | engine-aware contracts: Python bronze = `write_deltalake append`; silver = `read_bronze` only + `overwrite`; row-count check via delta-rs not `spark.table` | M |
| 12 | `fabric-project-initializer` | scaffolds PySpark utils + config | write `engine` + `schema_enabled` into `project-config.yml`; scaffold Python utilities notebook when engine=python; copy Python reference set | M |
| 13 | `reference/m-conversion-risk-catalog.md` | 30 risks assessed for Spark | add an **engine column / Python addendum**: some risks ease in polars (e.g. pivot/unpivot), others worsen (large-data joins, anything assuming distributed memory) | M |
| 14 | README + `_Documentation/pipeline-workflow.md` | PySpark narrative | document the toggle, decision matrix, Python limitations | S |
| 15 | `tests/` | regression on PySpark output | add Python-engine fixtures: builder output shape, converter mapping, validator engine-branch | M |

**Key finding on the structure hook (#10):** `validate-fabric-structure.py` does **not** enforce the kernel name today — `_validate_ipynb_shape()` only checks `nbformat==4`, non-empty `cells`, and `metadata.dependencies.lakehouse`. So a Python-kernel notebook with a valid lakehouse binding **passes the hook unchanged**. The only real conflict is the **silver forbidden-pattern list**, which is Spark-specific and must gain a Python branch (ban polars external reads, keep `read_bronze` requirement). The hook's docstring says "synapse_pyspark kernel" but the code never checks it — docstring is stale, not a blocker.

---

## 7. Design options & recommendations

### 7.1 Where the toggle lives
**Recommend: `userConfig.notebook_engine` (default `pyspark`) + an orchestrator `--engine python|pyspark` flag override**, asked in Stage 1 if unset. This mirrors the existing `--dry-run`/`--sample` flag pattern and the existing userConfig precedent. Persist the chosen engine into `project-config.yml` and Section 0 so incremental re-runs stay consistent (mixing engines in one project is out of scope for v1 — enforce "one engine per project").

### 7.2 Builder strategy — parameterize vs fork
| Option | Pros | Cons |
|---|---|---|
| **A. Parameterize existing 2 builders by `engine`** (recommended) | one agent per layer; orchestrator fan-out unchanged; shared layer-semantics (bronze=append, silver=read_bronze-only); engine picks reference set | each agent prompt grows; must be disciplined about "read the engine guide, not the other" |
| B. Fork 4 agents (`*-python`, `*-pyspark`) | each agent simpler/cleaner | doubles agent count + maintenance; orchestrator must branch agent type; description sprawl |

**Recommendation: Option A.** The layer *contracts* (bronze append-only + metadata; silver bronze-only + overwrite) are **engine-independent**; only the *codegen idiom* changes. Pass `engine` in the Stage 8/9 builder prompt; the builder reads `python-style-guide.md`/`python-delta-patterns.md` when `engine=python`, else the PySpark guides. Broaden each agent's `description` to "PySpark **or Python**."

### 7.3 Converter strategy
**Recommend: add `--target python|pyspark` to the existing converter skill** (shared M parser + dependency analysis; swap only the code-emitter). Forking a whole second skill duplicates the M lexer. The emitter is the only engine-specific half.

### 7.4 Engine advisory — DE-SCOPED for v1 (no source-volume signal exists)
**This was originally proposed as a profiling advisory; it is not viable as designed.** Per the §2 correction, the migration pipeline never profiles sources and has no row count or size at planning time — it only holds M code. So the toggle should be a **pure user decision** with no data-driven OOM warning in v1. Options if an advisory is wanted *later*, in rough order of effort/value:

1. **(v1 — chosen) No advisory.** Toggle is authoritative. Document the Python single-node memory caveat in the README + the approval screen text so the user makes an informed choice. Zero new machinery.
2. **Static M heuristic (low confidence).** At risk-scan time, flag output entities whose M sources are unbounded relational pulls (`Sql.Database`/`AnalysisServices` with no `Table.FirstN`, no date/range filter) as "potentially large for single-node Python." Cheap (reuses the M-analysis pass) but easily wrong — a filtered query can still be huge, an unfiltered one tiny.
3. **Real source sizing (scope expansion, not recommended for v1).** Add an optional stage that connects to the live sources and measures size (`sp_spaceused` / `os.path.getsize` / `rows × avg_row_bytes`). This breaks the offline-by-design property, needs source credentials, and would require extending `data-profiler` to emit a byte/MB figure (it currently emits only `total_rows`). Only worth it if engine mis-selection becomes a real support cost.

**Recommendation: option 1 for v1.** Honor the user's "100 % one engine" toggle exactly; surface the memory caveat as *documentation*, not as a gate.

---

## 8. Open questions / de-risking (do these before building)

1. **★ Exact Python-kernel `.ipynb` metadata (BLOCKER).** Not documented as JSON. The doc only warns: *"Make sure the language and kernel properties in notebook metadata of the public API payload are set properly."* PySpark today uses:
   ```json
   "kernel_info": {"name": "synapse_pyspark"},
   "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark"},
   "language_info": {"name": "python"}
   ```
   Best-known Python equivalent (TO CONFIRM): kernel name `jupyter` with a `microsoft.language: "python"` hint, e.g.
   ```json
   "kernel_info": {"name": "jupyter"},
   "kernelspec": {"name": "jupyter", "display_name": "Python (jupyter)", "language": "python"},
   "language_info": {"name": "python"},
   "microsoft": {"language": "python", "language_group": "jupyter"}
   ```
   **De-risk:** create one Python notebook in the Fabric UI, export it with the plugin's `fabric-cli-runner` (`fab notebook export`) and inspect `notebook-content.ipynb` metadata. **This single artifact unblocks the whole template.** Step 0 of implementation.
2. **Schema-enabled vs classic lakehouse.** Confirm the target lakehouses' schema mode and bake `schema_enabled` into `project-config.yml` so `table_path()` chooses `Tables/dbo/<n>` vs `Tables/<n>` (§5).
3. **delta-rs merge maturity.** Confirm `DeltaTable.merge(...)` covers the upsert patterns the gold/silver templates need on the pinned runtime; fall back to read-modify-overwrite for small tables if a merge feature is missing.
4. **`%run` utilities as a notebook item.** Confirm the scaffolded `nb_utils_config` deploys as a notebook item (not a `.py` resource) so `%run` resolves in Python notebooks (§3.6).
5. **Row-count / validation cost.** `pl.read_delta(path).height` materializes; prefer `DeltaTable(path).to_pyarrow_dataset().count_rows()` or a duckdb `count(*)` over `delta_scan` to avoid loading the table just to validate.

---

## 9. Proposed implementation slices (vertical, demoable)

Each slice is end-to-end runnable on the bundled `--sample` dataflows in `--dry-run` (no Fabric access). TDD per global rules: failing test first.

- **Slice 0 — Metadata spike (de-risk #1).** Obtain & record the real Python-notebook metadata JSON in `reference/python-notebook-metadata.md`. *Test:* a deployed Python notebook round-trips through `fab` as a Python notebook. *(One-off spike — flag as not-TDD.)*
- **Slice 1 — Toggle plumbing.** `userConfig.notebook_engine` + `--engine` flag + Section 0 + `project-config.yml` field. *Test:* orchestrator records engine; default stays `pyspark`; PySpark path byte-for-byte unchanged.
- **Slice 2 — Python reference set + utilities notebook.** `python-style-guide.md`, `python-delta-patterns.md`, Python `nb_utils_config` (incl. `table_path()` resolver). *Test:* utilities notebook is valid `.ipynb`, helpers importable via `%run` shape.
- **Slice 3 — Python bronze builder path.** `engine=python` emits a polars+delta-rs bronze notebook. *Test:* output is valid Python-kernel `.ipynb`, append + `schema_mode="merge"`, metadata cols present, passes engine-aware hook + validator.
- **Slice 4 — Python silver builder path.** `read_bronze()`-only, polars transforms, overwrite write. *Test:* engine-aware structure hook passes; no external reads; round-trips bronze→silver.
- **Slice 5 — M→Python converter.** `--target python` emits polars. *Test:* the existing converter regression fixtures get a polars-target expectation set.
- **Slice 6 — Engine-aware gates.** Branch `validate-fabric-structure.py` + `fabric-pipeline-validator` on engine. *Test:* PySpark fixtures still pass; Python fixtures pass; cross-contamination (Spark idiom in a Python notebook) fails.
- **Slice 7 — Risk-catalog addendum + docs.** Engine column on the 30 risks; README/workflow toggle docs. *Test:* catalog parses; regression suite green.
- **Slice 8 — (Dropped for v1) engine advisory.** No source-volume signal exists in the migration pipeline (see §2 correction / §7.4). Replace with a **documentation task**: state the Python single-node memory caveat in the README and in the Stage-7 approval text so the user chooses the engine informed. No code, no gate.

---

## 10. Testing & success criteria

**Success =** a user sets `notebook_engine: python`, runs the orchestrator on the sample dataflows, and gets valid **Python-kernel** bronze + silver `.ipynb` notebooks that (a) deploy via `fab` as Python notebooks, (b) write Delta to the correct `Tables[/dbo]/<name>` path with no "Unidentified" stragglers, (c) read bronze→silver successfully in one run, and (d) pass the engine-aware hook + validator — **while the existing PySpark path is byte-for-byte unchanged when `engine=pyspark`**.

**Test matrix:**
- Regression: every existing PySpark test green (default engine).
- Builder output shape: Python bronze/silver are valid `.ipynb`, correct kernel metadata, correct write modes.
- Converter: M→polars fixtures (mirror the M→PySpark fixtures).
- Gates: engine-branch unit tests for the hook and validator; negative tests for cross-engine leakage.
- Integration (`--sample --dry-run`): full orchestrator run on both engines, diffed against golden notebooks.
- Runtime (manual, needs Fabric): bronze→silver round-trip confirming table registration (§5).

**Security/safety:** no new secrets; `notebookutils.credentials.getSecret` path reused for SQL sources; generated code must not embed connection strings (same rule as PySpark path). No local absolute paths in any generated reference/template file (use `${CLAUDE_PLUGIN_ROOT}` / lakehouse-relative paths).

---

## 11. Sources

- [Choosing Between Python and PySpark Notebooks in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-engineering/fabric-notebook-selection-guide)
- [Use Python experience on Notebook — Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-engineering/using-python-experience-on-notebook)
- [write_deltalake "Unidentified" table registration — Fabric Community](https://community.fabric.microsoft.com/t5/Data-Engineering/write-deltalake-with-Python-Notebook-is-creating-an-quot/m-p/4407839)
- [QuickTest: Switching Between Fabric Python and PySpark Notebooks — fabric.guru](https://fabric.guru/quicktest-switching-between-fabric-python-and-pyspark-notebooks)
- [delta-rs (delta-io) docs](https://delta-io.github.io/delta-rs/) · [DuckDB docs](https://duckdb.org/) · [Polars docs](https://pola.rs/)
- Plugin internals reviewed: `agents/fabric-migration-orchestrator`, `agents/fabric-bronze-builder`, `agents/fabric-silver-builder`, `agents/fabric-pipeline-validator`, `skills/m-to-pyspark-converter`, `reference/{notebook-template,delta-lake-patterns,pyspark-style-guide}.md`, `hooks/validate-fabric-structure.py`, `.claude-plugin/plugin.json`.
