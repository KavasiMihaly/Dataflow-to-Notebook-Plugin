# M Conversion Risk Catalog

This catalog documents the 30 known Power Query M patterns that need special handling when converted to PySpark. Each entry has a stable `RISK-NN` ID, severity, detection signature, and recommended mitigation. The `m-query-analyst` agent scans .pq files for these patterns during Stage 4. The bronze and silver builders consult this catalog to wrap risky conversions in **HIGH RISK / HUMAN REVIEW REQUIRED** isolation cells.

**Source:** synthesized from real-world Gen1 → Fabric migration of 8 dataflows / 37 queries / 16 notebooks (RISK-01..RISK-15), plus 15 community-submitted patterns from GitHub issues #1–14, #16 (RISK-16..RISK-30). PySpark equivalents for RISK-16..RISK-30 verified against Microsoft Learn (Power Query M reference, Fabric / OneLake docs) and Apache Spark 4.1 documentation — see `_Research/m-patterns-15-conversion-research.md`.

---

## How to use this catalog

Each entry has:
- **RISK-NN** — stable identifier (used in JSON envelopes and notebook risk markers)
- **Severity** — Low / Medium / High
- **Detection** — regex/string the analyst scans for
- **Best-effort PySpark** — the converter emits this code
- **Python:** — engine-applicability note for `notebook_engine: python` (see below)
- **Risk marker decision** — `clean` (no marker), `marked` (HIGH RISK cell), `todo-only` (TODO with no PySpark)

---

## Engine applicability (`pyspark` | `python`)

Severities and detection signatures are **engine-independent** — the `m-query-analyst` scans the same patterns regardless of `notebook_engine`. The **mitigation idiom**, however, changes with the engine, so every RISK entry carries a `**Python:**` line tagged with one of four markers describing how the risk shifts on the single-node Python engine (polars / duckdb / delta-rs):

| Marker | Meaning |
|---|---|
| **ease** | polars/delta-rs make this *simpler or safer* than Spark — usually because a distributed-execution hazard (unordered DataFrames, non-sequential IDs, ANSI cast job-kill, action-vs-transformation cost) disappears on a single node. A `marked`/Medium risk may downgrade toward `clean`. |
| **worsen** | The single-node 16 GB ceiling makes this *riskier* — anything that assumes distributed memory (large joins, fan-out of a serial Excel read). Size against memory before choosing `python`. |
| **N-A** | Spark-only; **no Python equivalent** (e.g. V-Order / Native Execution Engine / Vegas cache — see the note under the severity matrix). |
| **unchanged** | Same effort and the same review concern on both engines (connector auth, regex string ops, OneLake-shortcut admin steps). |

These markers are advisory for human reviewers and the Python builders; they do **not** change the per-occurrence severity the analyst reports.

---

## Risk markers

When a builder emits PySpark for a `marked` pattern, wrap it like this:

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: <Pattern Name> (RISK-NN)
# Original M:
#   <copy of M expression>
# Best-effort PySpark:
<pyspark code>
# REVIEW: <specific concern, e.g., "container name must match OneLake shortcut">
# See: ${CLAUDE_PLUGIN_ROOT}/reference/m-conversion-risk-catalog.md#risk-NN
# === END HIGH RISK ===
```

For `todo-only` patterns, no PySpark is emitted — just:

```python
# TODO: convert <pattern> manually — see m-conversion-risk-catalog.md#risk-NN
# Original M:
#   <expression>
```

---

## RISK-01 — `AzureStorage.Blobs` (High, marked)

**Detection:** `AzureStorage\.Blobs\s*\(`

**Why risky:** Power Query connector with no PySpark equivalent. Authentication and path semantics differ entirely.

**Best-effort PySpark:**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: AzureStorage.Blobs (RISK-01)
# Original M: AzureStorage.Blobs("https://<account>.blob.core.windows.net/")
# Best-effort PySpark:
df_raw = spark.read.format("csv") \
    .option("header", "true") \
    .load("abfss://<container>@<account>.dfs.core.windows.net/<path>")
# REVIEW: container/account must match your OneLake shortcut OR workspace identity must
# have read access on the storage account. Update path if migrating to OneLake-relative.
# See: m-conversion-risk-catalog.md#risk-01
# === END HIGH RISK ===
```

**Python:** unchanged — still HIGH RISK. polars reads the same blob/OneLake path (`pl.read_csv` over the `/lakehouse/default/Files/...` mount or an `abfss://` path); the connector/auth/path-semantics review concern is engine-independent.

---

## RISK-02 — Custom M Functions / Combine Files Pattern (Medium, marked)

**Detection:** `\([\w\s,]*\)\s*=>\s*let` (lambda definition) — particularly when paired with helper queries `Parameter`, `Sample file`, `Transform Sample file`, `Transform file` in the same dataflow.

**Why risky:** Power Query's row-level function invocation has no PySpark equivalent — Spark reads all files in a folder declaratively.

**Best-effort PySpark (when refactor strategy = absorb):**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Combine Files (RISK-02) — absorbed
# Original: function applied per file via Table.AddColumn over filtered file list
# Best-effort PySpark:
df_raw = spark.read.format("csv") \
    .option("header", "true") \
    .option("pathGlobFilter", "*street*.csv") \
    .load("abfss://<container>@<account>.dfs.core.windows.net/<folder>/")
# REVIEW: confirm the path glob captures the intended files. The 4 helper queries
# (Parameter, Sample file, Transform Sample file, Transform file) are not needed.
# === END HIGH RISK ===
```

**Python:** ease — polars reads a whole folder declaratively too: `pl.read_csv("/lakehouse/default/Files/<folder>/*street*.csv")` (or `glob` + `pl.concat(..., how="diagonal_relaxed")` for multi-file). The per-file M function still has no equivalent, but single-node makes the combined read simpler to reason about; still review the glob.

---

## RISK-03 — `Excel.Workbook` (High, marked)

**Detection:** `Excel\.Workbook\s*\(`

**Why risky:** No native PySpark Excel reader. Three mitigation strategies are documented in `migration-design.md` Section 5; the chosen strategy controls which best-effort code is emitted.

**Best-effort PySpark — pandas+openpyxl (default if strategy unset):**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Excel.Workbook (RISK-03)
# Strategy: pandas+openpyxl in-cell (limits parallelism for large files)
import pandas as pd
df_pd = pd.read_excel(source_path, sheet_name="<sheet>", skiprows=4)
df_raw = spark.createDataFrame(df_pd)
# REVIEW: pandas reads serialize for large files. Consider pre-converting to CSV
# in a one-time prep notebook for files > 100 MB.
# === END HIGH RISK ===
```

**Alternative strategies** (chosen via `migration-analyst`):
- `pre-convert-csv` — emit a separate prep notebook + bronze reads CSV
- `spark-excel-maven` — `spark.read.format("com.crealytics.spark.excel")` (requires environment config)

**Python:** worsen — the default in-cell read (`pd.read_excel` / `pl.read_excel`) stays single-threaded AND there is no `spark.createDataFrame` to fan the result out to a cluster, so large workbooks press harder against the 16 GB single-node ceiling. Prefer the `pre-convert-csv` strategy on the Python engine for files over ~100 MB (`spark-excel-maven` is Spark-only — N-A here).

---

## RISK-04 — `Table.Skip` (Low, clean)

**Detection:** `Table\.Skip\s*\(`

**Why risky:** Different mechanism in PySpark, but conversion is mechanical.

**PySpark:**

```python
# For pandas read_excel: skiprows=N
# For spark.read.csv: .option("skipRows", N) (Spark 3.4+) OR
df_raw = df_raw.zipWithIndex().filter(lambda x: x[1] >= N).map(lambda x: x[0])
```

**Python:** ease — `pl.read_csv(path, skip_rows=N)` on read, or `df.slice(N)` / `df.tail(-N)` on a frame. No `zipWithIndex` RDD hack; row order is deterministic on a single node.

---

## RISK-05 — `Table.UnpivotOtherColumns` (Medium, clean)

**Detection:** `Table\.UnpivotOtherColumns\s*\(`

**PySpark:**

```python
# Hardcoded column list:
value_columns = ["2020", "2021", "2022", "2023"]
stack_expr = ", ".join([f"'{c}', `{c}`" for c in value_columns])
df = df.selectExpr(
    "id_col_1", "id_col_2",
    f"stack({len(value_columns)}, {stack_expr}) as (year, value)"
)
```

**Python:** ease — first-class `df.unpivot(index=[id_cols], on=value_columns, variable_name="year", value_name="value")`. No `stack()` string-building or `selectExpr`; the column list is a plain Python list.

---

## RISK-06 — `Table.Pivot` (Medium, clean)

**Detection:** `Table\.Pivot\s*\(`

**PySpark:**

```python
# Static pivot values (faster, deterministic):
distinct_vals = ["births", "deaths", "natchange"]
df = df.groupBy("LSOA Code").pivot("Attribute.1", distinct_vals).agg(F.first("Value"))

# Dynamic distinct values (one extra collect):
distinct_vals = [r[0] for r in df.select("Attribute.1").distinct().collect()]
df = df.groupBy("LSOA Code").pivot("Attribute.1", distinct_vals).agg(F.first("Value"))
```

**Python:** ease — `df.pivot(on="Attribute.1", index="LSOA Code", values="Value", aggregate_function="first")`. polars discovers the distinct pivot values itself (no extra `.distinct().collect()` round-trip) and the operation is eager/in-memory.

---

## RISK-07 — `Splitter.SplitTextByEachDelimiter` (Low, clean)

**Detection:** `Splitter\.SplitTextByEachDelimiter\b`

**PySpark:**

```python
# Split {metric}_{year} on the LAST underscore:
df = df.withColumn("metric", F.regexp_extract(F.col("Attribute"), r'^(.+)_(\d+)$', 1))
df = df.withColumn("year",   F.regexp_extract(F.col("Attribute"), r'^(.+)_(\d+)$', 2))
```

**Python:** unchanged — same regex approach: `pl.col("Attribute").str.extract(r'^(.+)_(\d+)$', 1)` for metric, group `2` for year. Pure column-expression work, identical effort on either engine.

---

## RISK-08 — `Text.BeforeDelimiter` / `Text.AfterDelimiter` (Low, clean)

**Detection:** `Text\.(Before|After)Delimiter\b`

**PySpark mappings:**

| M | PySpark |
|---|---|
| `Text.BeforeDelimiter(col, " -", 0)` | `F.split(F.col("col"), " -")[0]` |
| `Text.BeforeDelimiter(col, " ", {0, RelativePosition.FromEnd})` | `F.regexp_extract(F.col("col"), r'^(.*)\s\S+$', 1)` |
| `Text.AfterDelimiter(col, "_", 0)` | `F.split(F.col("col"), "_")[1]` |

**Python:** unchanged — `pl.col("col").str.split(" -").list.first()` (before) / `.list.get(1)` (after), or `str.extract` for the from-end form. Same string-op effort.

---

## RISK-09 — `Table.TransformColumnTypes` with 50+ columns (Low, clean)

**Detection:** `Table\.TransformColumnTypes\s*\(` with 50+ pairs in the type list.

**PySpark (recommended):** define a `StructType` schema and pass to `spark.read.csv(..., schema=schema)` to avoid post-read casts.

**Python:** ease — pass a `schema_overrides={col: pl.Int64, ...}` dict (or full `schema=`) to `pl.read_csv` to type-on-read, or `df.cast({col: dtype, ...})` for a one-shot bulk cast. The polars type map lives in the converter's §4 addendum (`Currency.Type`→`pl.Decimal(19,4)`, etc.).

---

## RISK-10 — `Table.NestedJoin` Left Outer Join (Low, clean)

**Detection:** `Table\.NestedJoin\s*\(`

**PySpark:**

```python
df_lookup = read_bronze("ofsted_rating")
df = df.join(df_lookup, df["URN"] == df_lookup["School ID"], "left")
```

**Note:** if the right side is in another dataflow, the right-side bronze notebook must run before the silver notebook that joins it.

**Python:** worsen — `df.join(read_bronze("ofsted_rating"), left_on="URN", right_on="School ID", how="left")` is mechanically simpler, BUT polars materializes both sides in single-node RAM; a join whose inputs comfortably fit a Spark cluster can OOM the 16 GB Python container. Keep the cross-dataflow ordering note, and on the Python engine size the joined tables against single-node memory before choosing this engine.

---

## RISK-11 — `Table.AddColumn` with conditional logic (Low, clean)

**Detection:** `Table\.AddColumn\s*\(` followed by `each\s+if`

**PySpark:**

```python
df = df.withColumn(
    "Ofsted Rank",
    F.when(F.col("Rating") == "Outstanding", 1)
     .when(F.col("Rating") == "Good", 2)
     .when(F.col("Rating") == "Requires Improvement", 3)
     .otherwise(None),
)
```

**Python:** unchanged — direct one-to-one: `pl.when(pl.col("Rating") == "Outstanding").then(1).when(...).otherwise(None).alias("Ofsted Rank")`. Same conditional-expression effort.

---

## RISK-12 — `Replacer.ReplaceText` chains (Low, clean)

**Detection:** Multiple sequential `Table\.ReplaceValue\s*\(`

**PySpark:**

```python
property_type_map = {"F": "Flat", "D": "Detached", "S": "Semi-Detached", "T": "Terraced", "O": "Other"}
df = df.replace(property_type_map, subset=["Property Type"])
```

**Python:** unchanged — `df.with_columns(pl.col("Property Type").replace(property_type_map))` (or `replace_strict` to error on unmapped values). Same dictionary-driven approach.

---

## RISK-13 — `Table.AddIndexColumn` (synthetic sequential ID) (High, marked)

**Detection:** `Table\.AddIndexColumn\s*\(`

**Why risky:** Spark is distributed — `monotonically_increasing_id()` is unique but not sequential. `row_number()` over a window requires a stable sort key.

**Best-effort PySpark:**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Table.AddIndexColumn (RISK-13)
# Best-effort PySpark — uses monotonically_increasing_id (unique but NOT sequential):
df = df.withColumn("Transaction ID", F.monotonically_increasing_id() + 1)
# REVIEW: if the original Transaction ID is a join key referenced elsewhere or
# must be reproducible, replace with row_number() over an explicit sort:
#   from pyspark.sql.window import Window
#   w = Window.orderBy("Transaction Date", "Post Code")
#   df = df.withColumn("Transaction ID", F.row_number().over(w))
# === END HIGH RISK ===
```

**Python:** ease — the distributed-ID hazard disappears on a single node. `df.with_row_index("Transaction ID", offset=1)` produces a genuinely sequential index (after an explicit `df.sort(...)` to fix ordering), so the HIGH RISK marker can usually downgrade to a clean conversion. Still review if the original ID is a reproducible cross-table join key.

---

## RISK-14 — `[Attributes]?[Hidden]?` optional record access (Low, clean — drop)

**Detection:** `\[Attributes\]\?\s*\[Hidden\]\?`

**PySpark:** drop the filter entirely. Spark's blob readers do not return system files.

**Python:** unchanged — same guidance: drop the filter. The `/lakehouse/default/Files/...` mount + `glob`/`pl.read_*` do not surface the `[Attributes][Hidden]` system records either.

---

## RISK-15 — Hardcoded blob paths (Medium, clean — refactor to config)

**Detection:** literal strings matching `https://[\w]+\.blob\.core\.windows\.net/` or `abfss://`

**PySpark (recommended):**

```python
# In nb_utils_config.py:
STORAGE_ACCOUNT = "<account>"
CONTAINERS = {"ukstat": "ukstat", "economic": "economicdata", "crime": "crimedata"}

def abfss_path(container_key, relative_path):
    container = CONTAINERS[container_key]
    return f"abfss://{container}@{STORAGE_ACCOUNT}.dfs.core.windows.net/{relative_path}"

# In bronze notebook:
df_raw = spark.read.format("csv") \
    .option("header", "true") \
    .load(abfss_path("ukstat", "Education/2023-2024/england_school_information.csv"))
```

**Python:** unchanged — same refactor-to-config recommendation. Put the `STORAGE_ACCOUNT`/`CONTAINERS` map and an `abfss_path()` (or mount-relative) resolver in the Python `nb_utils_config` notebook; the bronze cell calls `pl.read_csv(abfss_path(...))`. No hard-coded literals on either engine.

---

## RISK-16 — `SharePoint.Files` (High, todo-only)

**Detection:** `SharePoint\.(Files|Contents|Tables)\s*\(`

**Why risky:** No native PySpark or Fabric notebook connector for SharePoint. The Microsoft-recommended migration path is a OneLake shortcut to the SharePoint document library (created once via the Fabric UI, NOT from the notebook) followed by a normal lakehouse read.

**Best-effort PySpark (todo-only — admin step required first):**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: SharePoint.Files (RISK-16)
# Original M: SharePoint.Files("https://contoso.sharepoint.com/sites/Sales", [ApiVersion=15])
# Migration is a TWO-STEP process:
#   Step 1 (one-time admin, in Fabric UI):
#     Lakehouse > Files > New shortcut > SharePoint Folder > pick the document library.
#     This creates a OneLake shortcut at Files/<shortcut_name>/.
#   Step 2 (in this notebook): read the shortcut path like any lakehouse path.
# Once Step 1 is done, replace this TODO with:
#   df_raw = (
#       spark.read
#            .format("csv")          # or parquet/json/excel depending on file type
#            .option("header", "true")
#            .load("Files/<shortcut_name>/<subfolder>/*.csv")
#   )
# REVIEW:
#   - Do NOT bypass with requests.get() against SharePoint Graph API — breaks workspace identity.
#   - SharePoint.Files recurses by default; use /**/*.<ext> glob to match.
#   - The M [Content] binary column has no Spark counterpart — pick a format at read time.
#   - If the M code routed on [Name] / [Extension] to different parsers, the notebook needs
#     a loop or input_file_name() + conditional logic.
# See: m-conversion-risk-catalog.md#risk-16
# See: https://learn.microsoft.com/fabric/onelake/create-onedrive-sharepoint-shortcut
# === END HIGH RISK ===
```

**Python:** unchanged — still HIGH RISK / todo-only. The migration path is the same engine-independent OneLake shortcut (one-time admin step in the Fabric UI) followed by a normal lakehouse read; on the Python engine Step 2 becomes `pl.read_csv("/lakehouse/default/Files/<shortcut_name>/**/*.csv")` over the mount.

---

## RISK-17 — `Table.ExpandRecordColumn` (Low, clean)

**Detection:** `Table\.ExpandRecordColumn\s*\(`

**Why risky:** Mechanical when the column is a `StructType`; needs different handling for `MapType`.

**PySpark:**

```python
# Simple flatten — all fields of the struct become top-level columns:
df = df.select("*", F.col("rec.*")).drop("rec")

# Explicit field list + renames (mirrors M's optional newColumnNames argument):
df = df.select(
    "*",
    F.col("rec.aa").alias("aa"),
    F.col("rec.bb").alias("bb"),
).drop("rec")
```

**Note:** if the column is `MapType` (JSON loaded as a map, not a struct), use `F.col("rec").getItem("aa").alias("aa")` instead — `rec.*` only works on structs. `select("*", "rec.*")` places struct fields at the end of the schema, which differs from M's ordering — reorder downstream if column order is load-bearing.

**Python:** unchanged — `df.unnest("rec")` flattens a struct column to top-level columns (rename via `pl.col("rec").struct.field("aa").alias("aa")`). For a map-typed column use `pl.col("rec").struct.field(...)` / `list.eval` equivalents. Same struct-vs-map distinction applies.

---

## RISK-18 — `Table.PromoteHeaders` (Medium, marked when post-load)

**Detection:** `Table\.PromoteHeaders\s*\(`

**Why risky:** 95% of usages immediately follow a connector — convert by setting `header=true` on the read. Post-load promotion (first row of an already-loaded DataFrame) is multi-step and easy to get wrong because Spark DataFrames are unordered.

**Best-effort PySpark — Context A (header in source file, preferred):**

```python
# Replace the PromoteHeaders step entirely with a read option:
df = (
    spark.read
         .option("header", "true")
         .csv("Files/sales.csv")
)
```

**Best-effort PySpark — Context B (post-load promotion):**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Table.PromoteHeaders (RISK-18) — post-load form
# Original M: Table.PromoteHeaders(#"Filtered Rows", [PromoteAllScalars=true])
# Best-effort PySpark — DataFrame is unordered, so we MUST add an index first:
from pyspark.sql.window import Window
df_with_idx = df.withColumn("__idx", F.row_number().over(Window.orderBy(F.monotonically_increasing_id())))
first_row = df_with_idx.filter(F.col("__idx") == 1).drop("__idx").first()
new_cols = [str(first_row[c]) if first_row[c] is not None else c for c in df.columns]
df = df_with_idx.filter(F.col("__idx") > 1).drop("__idx").toDF(*new_cols)
# REVIEW: Spark column names cannot contain . , ; { } ( ) \n \t = (space). Sanitize the
# promoted names or wrap them in backticks downstream. PromoteAllScalars=true in M
# stringifies non-text scalars with a culture; str(...) here uses Python repr which
# differs from M's en-US default for dates — use F.date_format(col, "M/d/yyyy") to
# mimic M output if downstream parsing depends on the exact name.
# See: m-conversion-risk-catalog.md#risk-18
# === END HIGH RISK ===
```

**Python:** ease — Context A is identical (`pl.read_csv(path, has_header=True)`). Context B (post-load promotion) is much safer: polars frames preserve row order, so there is no Spark "unordered DataFrame" hazard — promote via `df.rename(dict(zip(df.columns, df.row(0))))` then `df.slice(1)`, no `monotonically_increasing_id()` window. The post-load form can usually drop the HIGH RISK marker.

---

## RISK-19 — `Text.BetweenDelimiters` (Medium, marked when non-default indices)

**Detection:** `Text\.BetweenDelimiters\s*\(`

**Why risky:** The simple form is one line of `regexp_extract`. Optional `startIndex` / `endIndex` parameters (selecting the Nth occurrence or using `RelativePosition.FromEnd`) have no clean Spark equivalent.

**PySpark — simple case:**

```python
import re

# Common case: between literal "(" and ")", first occurrence.
df = df.withColumn(
    "between",
    F.regexp_extract(F.col("raw"), r"\((.*?)\)", 1),
)

# General helper for arbitrary delimiters — escape regex metachars and use lazy match:
def between_delimiters(col, start, end):
    pat = re.escape(start) + r"(.*?)" + re.escape(end)
    return F.regexp_extract(col, pat, 1)
```

**Note:** `regexp_extract` returns empty string `""` on no match; M `Text.BetweenDelimiters` returns `null`. Wrap with `F.when(F.length(...) > 0, ...).otherwise(F.lit(None))` if downstream code distinguishes null from empty. ALWAYS `re.escape` literal delimiter strings — `Text.BetweenDelimiters` treats them literally; `regexp_extract` interprets them as regex.

**Mark as HIGH RISK if:** the M call has `startIndex` or `endIndex` arguments (e.g. `Text.BetweenDelimiters(_, "[", "]", 2)` for the 3rd occurrence), since `regexp_extract` only returns the first match. Use `regexp_extract_all` (Spark 3.5+) + index lookup, and flag for review.

**Python:** unchanged — `pl.col("raw").str.extract(r"\((.*?)\)", 1)` for the simple case (returns `null` on no match — closer to M than Spark's empty string). The Nth-occurrence form is still HIGH RISK: use `str.extract_all` + `list.get(n)` and flag for review, exactly as on Spark.

---

## RISK-20 — `Table.ReplaceErrorValues` (High, marked)

**Detection:** `Table\.ReplaceErrorValues\s*\(`

**Why risky:** Spark and M have fundamentally different error models — M errors are first-class values that flow through expressions; Spark either silently coerces to NULL (legacy mode) or throws an exception that kills the whole job (ANSI mode, the modern default). There is no exact analogue. The right pattern depends on what *raised* the error upstream.

**Best-effort PySpark:**

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Table.ReplaceErrorValues (RISK-20)
# Original M: Table.ReplaceErrorValues(t, {{"sales", 0}, {"qty", 0}})
# M error values most commonly originate at type conversion. Spark equivalent:
#   1. Use a permissive cast (returns NULL on failure in legacy mode)
#   2. fillna() with the per-column replacement map
df = (
    df.withColumn("sales", F.col("sales").cast("double"))   # bad strings -> NULL
      .withColumn("qty",   F.col("qty").cast("int"))
      .fillna({"sales": 0, "qty": 0})
)

# If source data contains Excel sentinel strings that aren't real M errors:
df = df.replace(["#REF!", "#VALUE!", "#N/A", "NA"], None).fillna({"sales": 0, "qty": 0})

# REVIEW:
#   - ANSI mode caveat: with spark.sql.ansi.enabled=true (modern default), cast("int") on
#     "abc" throws — the converted notebook will fail loudly where the M version silently
#     produced an error value. Use F.try_cast (Spark 3.5+) for parity:
#       F.coalesce(F.try_cast(F.col("sales"), "double"), F.lit(0))
#   - If the M dataflow used `try ... otherwise ...`, that maps directly to
#     F.coalesce(F.try_cast(...), default).
#   - Per-column M replacement map ({{"A","x"},{"B","y"}}) → df.fillna({"A":"x","B":"y"}).
# See: m-conversion-risk-catalog.md#risk-20
# === END HIGH RISK ===
```

**Python:** ease — no ANSI-mode dichotomy. `pl.col("sales").cast(pl.Float64, strict=False)` returns `null` on a bad value (never kills the run), then `.fill_null(0)`; the per-column map is `df.fill_null({"sales": 0, "qty": 0})`. The "loud failure vs silent null" caveat that makes this HIGH RISK on Spark does not arise.

---

## RISK-21 — `Table.TransformColumnNames` (Low, clean)

**Detection:** `Table\.TransformColumnNames\s*\(`

**PySpark:**

```python
# Apply a function to every column name in one shot:
df = df.toDF(*[name_fn(c) for c in df.columns])

# Typical conversion — lowercase + strip + underscore-separated:
df = df.toDF(*[c.strip().lower().replace(" ", "_") for c in df.columns])
```

**Note:** `toDF(*names)` requires `len(names) == len(df.columns)` and every element must be a string (no `None`). M's `MaxLength` option for truncation + dedup is non-trivial — emit `[name_fn(c)[:max_len] for c in df.columns]` and then assert `len(set(...)) == len(...)` rather than silently deduping. Avoid chaining `withColumnRenamed` N times — it builds an O(N²) logical plan; use `toDF` or `select(*aliased_cols)`.

**Python:** ease — `df.rename({old: name_fn(old) for old in df.columns})` applies all renames in one call with no O(N²) plan to avoid (the chained-`withColumnRenamed` pitfall is Spark-specific). The `MaxLength` truncation + dedup-assert guidance still applies.

---

## RISK-22 — `Text.From` (Low, clean)

**Detection:** `Text\.From\s*\(`

**PySpark:**

```python
# Default (ISO format for dates, Spark default repr for numbers):
df = df.withColumn("s", F.col("v").cast("string"))

# Culture-aware date formatting (use date_format / format_number when culture matters):
df = df.withColumn("s_de", F.date_format(F.col("v"), "dd.MM.yyyy HH:mm:ss"))
```

**Note:** `cast("string")` on a date yields ISO (`2024-06-24`), NOT M's en-US default (`6/24/2024 2:32:22 PM`). If downstream pipelines parse the string back, use `F.date_format(col, "M/d/yyyy h:mm:ss a")` to mimic M. `Text.From(null) -> null` and PySpark `cast` preserves NULL identically. `Text.From(true) -> "TRUE"` (uppercase); PySpark `cast("string")` on bool yields `"true"` (lowercase) — wrap with `F.upper(...)` if downstream code does `== "TRUE"`.

**Python:** unchanged — `pl.col("v").cast(pl.Utf8)` for the default; `pl.col("v").dt.strftime("%-m/%-d/%Y %-I:%M:%S %p")` to mimic M's en-US format. The same ISO-vs-en-US date and `"true"`-vs-`"TRUE"` boolean caveats apply (cast yields lowercase `"true"`; wrap with `.str.to_uppercase()`).

---

## RISK-23 — `Text.Lower` (Low, clean)

**Detection:** `Text\.Lower\s*\(`

**PySpark:**

```python
df = df.withColumn("lower_name", F.lower(F.col("name")))
```

**Note:** `F.lower` is locale-insensitive (UTF-16 simple case folding). M's optional `culture` arg enables Turkic dotless-I handling (`İ -> i`); Spark doesn't. Almost never matters but flag if culture was explicitly passed in the M code. NULL handling matches M exactly.

**Python:** unchanged — `pl.col("name").str.to_lowercase()`. Also locale-insensitive (no Turkic culture handling); same "flag if a culture arg was passed" caveat, same NULL behaviour.

---

## RISK-24 — `Text.Trim` (Low default, Medium with chars)

**Detection:** `Text\.Trim\s*\(`

**PySpark — default whitespace trim:**

```python
df = df.withColumn("clean", F.trim(F.col("raw")))
```

**PySpark — custom trim characters (Spark 3.5+):**

```python
# M form: Text.Trim(x, {"<", ">", "/"})
df = df.withColumn("clean", F.btrim(F.col("raw"), F.lit("<>/")))

# Pre-Spark 3.5 fallback:
df = df.withColumn("clean", F.regexp_replace(F.col("raw"), r"^[<>/]+|[<>/]+$", ""))
```

**Note:** `F.trim` only strips ASCII whitespace + a few Unicode spaces. M strips all Unicode whitespace; for high-fidelity Unicode trim use `F.regexp_replace(col, r"^\s+|\s+$", "")`. Verify Fabric's current Spark version before committing to `btrim` — older Fabric runtimes (Spark < 3.5) need the regexp_replace fallback.

**Python:** unchanged — `pl.col("raw").str.strip_chars()` (default whitespace) or `.str.strip_chars("<>/")` (custom char set, no Spark-version gate needed). For full Unicode parity use `.str.replace_all(r"^\s+|\s+$", "")`. Same Unicode-whitespace caveat.

---

## RISK-25 — `List.RemoveNulls` (Low, clean — context-dependent)

**Detection:** `List\.RemoveNulls\s*\(`

**PySpark — three contexts; pick by inspecting the M call site:**

```python
# Context A (most common): M was List.RemoveNulls(Table.Column(t, "x")) — drop rows.
df = df.dropna(subset=["value"])

# Context B: array column, remove nulls within each row's array.
df = df.withColumn("arr_clean", F.filter(F.col("arr"), lambda x: x.isNotNull()))

# Context C: hardcoded literal Python list (M list was a literal).
clean = [x for x in lst if x is not None]
```

**Note:** Default to Context A unless the M expression is clearly a literal list or an array-column transform. `F.filter` with a lambda is Spark 3.1+; on earlier versions use `F.expr("filter(arr, x -> x is not null)")`.

**Python:** unchanged — same three contexts. Context A: `df.drop_nulls(subset=["value"])`; Context B (array column): `pl.col("arr").list.drop_nulls()`; Context C (literal): `[x for x in lst if x is not None]`. No Spark-version gate on the array form.

---

## RISK-26 — `List.Distinct` (Low, clean — context-dependent)

**Detection:** `List\.Distinct\s*\(`

**PySpark — three contexts:**

```python
# Context A: distinct rows / column values (most common M usage).
df = df.dropDuplicates(["value"])   # NOT df.distinct() unless ALL columns matter

# Context B: distinct elements within an array column.
df = df.withColumn("arr_d", F.array_distinct(F.col("arr")))

# Context C: literal Python list — preserve insertion order:
distinct = list(dict.fromkeys(lst))
```

**Note:** `df.distinct()` deduplicates *all columns together* — almost never what `List.Distinct(Table.Column(t,"x"))` means. M `List.Distinct(lst, Comparer.OrdinalIgnoreCase)` requires deduping on a case-folded key: `df.dropDuplicates([F.lower(F.col("x")).alias("__k")])` semantics. `array_distinct` order-preservation: documented order-preserving in Spark 3.5+; on older versions emit the literal-list pattern via `F.expr("transform(...)")` + manual dedupe if order is load-bearing.

**Python:** unchanged — same three contexts. Context A: `df.unique(subset=["value"], maintain_order=True)` (NOT bare `df.unique()` unless all columns matter); Context B (array column): `pl.col("arr").list.unique(maintain_order=True)`; Context C (literal): `list(dict.fromkeys(lst))`. For OrdinalIgnoreCase dedup, key on `pl.col("x").str.to_lowercase()`.

---

## RISK-27 — `List.Count` (Medium, marked when ambiguous context)

**Detection:** `List\.Count\s*\(`

**Why risky:** Context determines whether you emit an action (`df.count()` — triggers a Spark job) or a column expression (`F.size(arr)`). Misclassification is expensive.

**Best-effort PySpark — three contexts:**

```python
# Context A: M was counting rows (e.g. List.Count(Table.Column(t,"x"))).
n = df.count()                            # scalar — triggers a job
df = df.agg(F.count("*").alias("n"))      # as a single-row DataFrame

# Context B: counting elements per row in an array column.
df = df.withColumn("n_items", F.size(F.col("arr")))

# Context C: hardcoded literal list.
n = len(lst)
```

**Note:** `df.count()` is an *action* — triggers a full job, can be expensive. If the value is only needed inside another expression, use `F.count("*").over(...)` or precompute and broadcast. `F.size(null_array)` returns `-1` in Spark legacy mode (`null` with `spark.sql.legacy.sizeOfNull=false`); M `List.Count(null)` errors. Wrap with `F.when(col.isNull(), 0).otherwise(F.size(col))` for parity.

**Python:** ease — no action-vs-transformation hazard, because polars is eager and single-node. Context A is a cheap `df.height` / `len(df)` (no Spark job to trigger or broadcast around); Context B (per-row array length) is `pl.col("arr").list.len()`; Context C is `len(lst)`. The "misclassification is expensive" worry that makes this Medium on Spark largely evaporates.

---

## RISK-28 — `List.Transform` (Medium, marked when transform uses scalar UDF)

**Detection:** `List\.Transform\s*\(`

**Why risky:** Context detection (literal / array column / column-of-rows) AND the converter MUST rewrite the inner transform to native `F.*` builtins. Falling back to a Python UDF breaks Catalyst optimization and runs slow.

**Best-effort PySpark — three contexts:**

```python
# Context A: literal list, M used a literal lambda.
result = [fn(x) for x in lst]

# Context B: array column — F.transform takes a Column-returning lambda.
df = df.withColumn("arr2", F.transform(F.col("arr"), lambda x: x + 1))

# Context C: column-of-rows (most common — M used List.Transform on a Table.Column).
# Vectorized — preferred:
df = df.withColumn("col2", F.lower(F.col("col")))   # if M was List.Transform(col, each Text.Lower(_))

# Last-resort UDF (slow — avoid):
my_udf = F.udf(fn, returnType=StringType())
df = df.withColumn("col2", my_udf(F.col("col")))
```

**Note:** `F.transform` lambda receives a `Column` argument — your transform body must use `F.*` functions, not Python-level operations. For context C, identify what `fn` does and rewrite to native column expressions (`F.lower`, `F.regexp_replace`, etc.) rather than defaulting to a UDF. M `List.Transform` over heterogeneous lists has no Spark equivalent — `F.transform` requires a typed array; flag for review.

**Python:** ease — the Catalyst-vs-UDF performance cliff does not exist in polars. Context B (array column): `pl.col("arr").list.eval(pl.element() + 1)`; Context C (column of values): a plain native expression like `pl.col("col").str.to_lowercase()`. Even a `.map_elements()` Python fallback is acceptable on small single-node data, so this drops from Medium toward a clean conversion.

---

## RISK-29 — `List.AnyTrue` (Medium, marked when context unclear)

**Detection:** `List\.AnyTrue\s*\(`

**Best-effort PySpark — four contexts:**

```python
# Context A: literal Python list of booleans.
result = any(lst)

# Context B: array column of booleans.
df = df.withColumn("any_true", F.exists(F.col("flags"), lambda x: x))
# Shorthand (note NULL caveat below):
df = df.withColumn("any_true", F.array_contains(F.col("flags"), True))

# Context C: aggregation across rows ("does ANY row have flag=true?").
df.select(F.max(F.col("flag").cast("int")).alias("any_true"))   # 1 if any TRUE, 0 if none

# Context D: row-level early-exit (M typically wrote List.AnyTrue({condition})).
n = df.filter(F.col("flag") == True).limit(1).count() > 0
```

**Note:** `F.array_contains(arr, True)` returns NULL if the array contains a NULL element; `F.exists(arr, lambda x: x)` ignores NULLs and matches M behavior. Context D still triggers a Spark job — push the boolean check upstream if possible. `F.exists` lambda must use `F.*` Column ops, not Python `if`.

**Python:** ease — no Spark-job concern for the row-level check (Context D). Context A: `any(lst)`; Context B (array column): `pl.col("flags").list.any()`; Context C (across rows): `df.select(pl.col("flag").any())`; Context D: `df.filter(pl.col("flag")).height > 0` — all cheap and eager on a single node. The "context unclear → mark Medium" caution mainly reflects Spark's job cost, which is gone here.

---

## RISK-30 — `Text.Combine` with separator (Low, clean — context-dependent)

**Detection:** `Text\.Combine\s*\(`

**Best-effort PySpark — three contexts (use `concat_ws`, NOT `concat`):**

```python
# Context A: combining separate columns with a separator.
df = df.withColumn("full", F.concat_ws(" | ", F.col("city"), F.col("state"), F.col("zip")))

# Context B: combining elements of an array column with a separator.
df = df.withColumn("joined", F.array_join(F.col("arr"), " | "))

# Context C: hardcoded literal list of strings in M.
s = " | ".join([x for x in lst if x is not None])
```

**Note:** ALWAYS use `F.concat_ws(sep, ...)`, NEVER `F.concat(...)` — `F.concat` has no separator AND propagates NULL (`F.concat("a", NULL) -> NULL`); `F.concat_ws` treats NULLs as empty strings, closer to M's "nulls are ignored" semantics. For an *array column* the correct function is `F.array_join(arr, sep)`, not `F.concat_ws`. For exact M parity (M skips nulls entirely, so `Text.Combine({"a", null, "b"}, ",")` → `"a,b"`, while `F.concat_ws("a", NULL, "b")` → `"a,,b"`), filter nulls first with `F.array_compact` (Spark 3.4+) before `F.array_join`. The shape `Text.Combine(list, sep)` is the array form — emit `F.array_join`, not `F.concat_ws`, when the first M argument is a list expression rather than separate columns.

**Python:** unchanged — separate columns: `pl.concat_str([pl.col("city"), pl.col("state"), pl.col("zip")], separator=" | ", ignore_nulls=True)`; array column: `pl.col("arr").list.join(" | ")`. Use `ignore_nulls=True` for M's null-skipping parity; same "array form vs separate-columns form" distinction.

> **NOTE:** the static `function_map.py` previously mapped `Text.Combine -> F.concat`, which is wrong when a separator is present. The catalog entry above is the canonical mitigation; the function map has been corrected to `F.concat_ws`.

---

## Severity-to-marker decision matrix

| Severity | Risk marker behavior | Examples |
|---|---|---|
| **High** | Always wrap in HIGH RISK cell | RISK-01, RISK-03, RISK-13, RISK-16, RISK-20 |
| **Medium** | HIGH RISK cell when refactor strategy needs review or context is ambiguous | RISK-02, RISK-05, RISK-06, RISK-15, RISK-18, RISK-19, RISK-27, RISK-28, RISK-29 |
| **Low** | Clean conversion — no marker | RISK-04, RISK-07–12, RISK-14, RISK-17, RISK-21–26, RISK-30 |

The `m-query-analyst` reports severity per detected occurrence; the builder applies the marker decision based on this table.

### Spark-only optimizations (N-A on the Python engine)

These are **not M patterns** (so they have no RISK-NN entry) but are the clearest **N-A** cases for the Python engine, called out here so reviewers don't look for a polars equivalent that doesn't exist:

- **V-Order / `spark.sql.parquet.vorder.enabled`** — Spark-only write optimization. No delta-rs/polars equivalent; drop it on the Python engine. A Python-written Delta table can be V-Order-optimized later by a separate Spark `OPTIMIZE` job or by the SQL endpoint's background optimization.
- **Native Execution Engine (NEE)** and the **Vegas cache** — Spark-runtime features with no single-node Python counterpart.

If the source PySpark notebooks (or `delta-lake-patterns.md` gold-layer guidance) set any of these, the Python builder simply omits them — they are performance tuning, not correctness, and the table remains queryable without them.

---

## Adding new patterns to the catalog

When `m-query-analyst` Pass 2 detects an M pattern not in this catalog, it appends an entry to `_Documentation/conversion-backlog.md` with status `Backlog`. To promote a backlog entry to a documented risk:

1. Confirm the pattern's PySpark equivalent (manual research)
2. Add a new `RISK-NN` section to this catalog with detection signature, severity, mitigation
3. Update `m-query-analyst/agent.md` if a special-case detection rule is needed
4. Move the backlog entry's status to `Documented`
5. Re-run plugin tests
