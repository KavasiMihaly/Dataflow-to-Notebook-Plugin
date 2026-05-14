# M Conversion Risk Catalog

This catalog documents the 15 known Power Query M patterns that need special handling when converted to PySpark. Each entry has a stable `RISK-NN` ID, severity, detection signature, and recommended mitigation. The `m-query-analyst` agent scans .pq files for these patterns during Stage 4. The bronze and silver builders consult this catalog to wrap risky conversions in **HIGH RISK / HUMAN REVIEW REQUIRED** isolation cells.

**Source:** synthesized from real-world Gen1 → Fabric migration of 8 dataflows / 37 queries / 16 notebooks.

---

## How to use this catalog

Each entry has:
- **RISK-NN** — stable identifier (used in JSON envelopes and notebook risk markers)
- **Severity** — Low / Medium / High
- **Detection** — regex/string the analyst scans for
- **Best-effort PySpark** — the converter emits this code
- **Risk marker decision** — `clean` (no marker), `marked` (HIGH RISK cell), `todo-only` (TODO with no PySpark)

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

---

## RISK-07 — `Splitter.SplitTextByEachDelimiter` (Low, clean)

**Detection:** `Splitter\.SplitTextByEachDelimiter\b`

**PySpark:**

```python
# Split {metric}_{year} on the LAST underscore:
df = df.withColumn("metric", F.regexp_extract(F.col("Attribute"), r'^(.+)_(\d+)$', 1))
df = df.withColumn("year",   F.regexp_extract(F.col("Attribute"), r'^(.+)_(\d+)$', 2))
```

---

## RISK-08 — `Text.BeforeDelimiter` / `Text.AfterDelimiter` (Low, clean)

**Detection:** `Text\.(Before|After)Delimiter\b`

**PySpark mappings:**

| M | PySpark |
|---|---|
| `Text.BeforeDelimiter(col, " -", 0)` | `F.split(F.col("col"), " -")[0]` |
| `Text.BeforeDelimiter(col, " ", {0, RelativePosition.FromEnd})` | `F.regexp_extract(F.col("col"), r'^(.*)\s\S+$', 1)` |
| `Text.AfterDelimiter(col, "_", 0)` | `F.split(F.col("col"), "_")[1]` |

---

## RISK-09 — `Table.TransformColumnTypes` with 50+ columns (Low, clean)

**Detection:** `Table\.TransformColumnTypes\s*\(` with 50+ pairs in the type list.

**PySpark (recommended):** define a `StructType` schema and pass to `spark.read.csv(..., schema=schema)` to avoid post-read casts.

---

## RISK-10 — `Table.NestedJoin` Left Outer Join (Low, clean)

**Detection:** `Table\.NestedJoin\s*\(`

**PySpark:**

```python
df_lookup = read_bronze("ofsted_rating")
df = df.join(df_lookup, df["URN"] == df_lookup["School ID"], "left")
```

**Note:** if the right side is in another dataflow, the right-side bronze notebook must run before the silver notebook that joins it.

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

---

## RISK-12 — `Replacer.ReplaceText` chains (Low, clean)

**Detection:** Multiple sequential `Table\.ReplaceValue\s*\(`

**PySpark:**

```python
property_type_map = {"F": "Flat", "D": "Detached", "S": "Semi-Detached", "T": "Terraced", "O": "Other"}
df = df.replace(property_type_map, subset=["Property Type"])
```

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

---

## RISK-14 — `[Attributes]?[Hidden]?` optional record access (Low, clean — drop)

**Detection:** `\[Attributes\]\?\s*\[Hidden\]\?`

**PySpark:** drop the filter entirely. Spark's blob readers do not return system files.

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

---

## Severity-to-marker decision matrix

| Severity | Risk marker behavior | Examples |
|---|---|---|
| **High** | Always wrap in HIGH RISK cell | RISK-01, RISK-03, RISK-13 |
| **Medium** | HIGH RISK cell when refactor strategy needs review | RISK-02, RISK-05, RISK-06, RISK-15 |
| **Low** | Clean conversion — no marker | RISK-04, RISK-07-12, RISK-14 |

The `m-query-analyst` reports severity per detected occurrence; the builder applies the marker decision based on this table.

---

## Adding new patterns to the catalog

When `m-query-analyst` Pass 2 detects an M pattern not in this catalog, it appends an entry to `_Documentation/conversion-backlog.md` with status `Backlog`. To promote a backlog entry to a documented risk:

1. Confirm the pattern's PySpark equivalent (manual research)
2. Add a new `RISK-NN` section to this catalog with detection signature, severity, mitigation
3. Update `m-query-analyst/agent.md` if a special-case detection rule is needed
4. Move the backlog entry's status to `Documented`
5. Re-run plugin tests
