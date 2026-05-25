# Research: 15 M-to-PySpark Pattern Conversions

Compiled: 2026-05-25
Sources: Microsoft Learn (Power Query M reference, Fabric / OneLake docs), Apache Spark official docs (PySpark 4.1).

These 15 patterns extend the fabric-dataflow-migration-toolkit M-to-PySpark risk catalog. Each entry below cites the M reference URL, the canonical PySpark equivalent (with Spark / Microsoft Learn URL), a severity rating, and gotchas. Snippets are intended to be drop-in for the catalog.

## Summary table

| #  | M Function                  | Severity | PySpark Function (canonical)                              | Primary source URL |
|----|-----------------------------|----------|-----------------------------------------------------------|--------------------|
| 1  | `SharePoint.Files`          | High     | OneLake SharePoint shortcut + `spark.read.format(...)`    | https://learn.microsoft.com/fabric/onelake/create-onedrive-sharepoint-shortcut |
| 2  | `Table.ExpandRecordColumn`  | Low      | `df.select("*", F.col("rec.*")).drop("rec")` (struct flatten) | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.select.html |
| 3  | `Table.PromoteHeaders`      | Medium   | `spark.read.option("header","true")...` OR `df.toDF(*first_row)` from already-loaded data | https://spark.apache.org/docs/latest/sql-data-sources-csv.html |
| 4  | `Text.BetweenDelimiters`    | Medium   | `F.regexp_extract(col, r"START(.*?)END", 1)`              | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.regexp_extract.html |
| 5  | `Table.ReplaceErrorValues`  | High     | `F.when(F.col(c).isNull(), lit).otherwise(...)` + safe-cast pattern | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.fillna.html |
| 6  | `Table.TransformColumnNames`| Low      | `df.toDF(*[fn(c) for c in df.columns])`                   | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.toDF.html |
| 7  | `Text.From`                 | Low      | `F.col(c).cast("string")`                                 | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.Column.cast.html |
| 8  | `Text.Lower`                | Low      | `F.lower(F.col(c))`                                       | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.lower.html |
| 9  | `Text.Trim`                 | Low      | `F.trim(F.col(c))`                                        | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.trim.html |
| 10 | `List.RemoveNulls`          | Low      | `df.dropna(subset=[c])` OR `F.filter(arr, lambda x: x.isNotNull())` | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.dropna.html |
| 11 | `List.Distinct`             | Low      | `df.dropDuplicates([c])` OR `F.array_distinct(arr)`       | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.array_distinct.html |
| 12 | `List.Count`                | Medium   | `df.count()` / `F.count()` OR `F.size(arr)` (depends on context) | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.size.html |
| 13 | `List.Transform`            | Medium   | `[fn(x) for x in lst]` (literal) OR `F.transform(arr, lambda x: ...)` (column) | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.transform.html |
| 14 | `List.AnyTrue`              | Medium   | `any(lst)` (literal) OR `F.exists(arr, lambda x: x)` (column) | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.exists.html |
| 15 | `Text.Combine` (w/ sep)     | Low      | `F.concat_ws(sep, *cols)` (NOT `F.concat` — no separator) | https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.concat_ws.html |

---

## Pattern-by-pattern details

### 1. SharePoint.Files

**M reference:** https://learn.microsoft.com/powerquery-m/sharepoint-files
**M semantics:** `SharePoint.Files(url as text, optional options as nullable record) as table` — returns a table containing one row per document found at the SharePoint site URL and all subfolders, with file metadata + a binary `Content` column the user typically drills into. Authenticates via Microsoft Entra (or workspace identity in Fabric Dataflow Gen2).
**PySpark equivalent (recommended pattern in Fabric):**
```python
# Step 1 (one-time, in Fabric UI): create a OneLake shortcut to the SharePoint
#   document library. Lakehouse > Files > New shortcut > SharePoint Folder.
# Step 2 (in notebook): read the files via the lakehouse-mounted path.
df = (
    spark.read
         .format("csv")          # or parquet/json/excel depending on file type
         .option("header", "true")
         .option("inferSchema", "true")
         .load("Files/sp_shortcut/Sales/*.csv")
)
```
**PySpark / Fabric reference:** https://learn.microsoft.com/fabric/onelake/create-onedrive-sharepoint-shortcut and https://blog.fabric.microsoft.com/en-US/blog/turning-everyday-documents-from-sharepoint-and-onedrive-into-analytics-ready-data-with-onelake-shortcuts/
**Severity:** **High** — there is no native PySpark SharePoint connector. Migration requires an out-of-notebook Fabric admin step (creating the OneLake shortcut), then the notebook reads files like normal lakehouse files. Authentication model changes: M used the user's Entra token at refresh; OneLake shortcuts now support workspace identity / service principal (preview / GA), which is the recommended Fabric-native path.
**Gotchas:**
- Do NOT attempt `requests.get(...)` against the SharePoint Graph API inside the notebook — that bypasses Fabric governance and breaks workspace identity. Always recommend a OneLake shortcut.
- `SharePoint.Files` recurses into all subfolders by default; the converted notebook must use a glob (`/**/*.csv`) or an explicit folder walk to match.
- The M `Content` binary column has no direct PySpark counterpart; the converted code must pick a format (`csv`, `parquet`, `excel`, etc.) at read time. Mark this for human review.
- For dataflows that depended on the `[Name]` / `[Extension]` columns to *route* to different parsers, the converted notebook needs a loop or `input_file_name()` + conditional logic.

### 2. Table.ExpandRecordColumn

**M reference:** https://learn.microsoft.com/powerquery-m/table-expandrecordcolumn
**M semantics:** `Table.ExpandRecordColumn(table, column, fieldNames, optional newColumnNames)` — for a column whose values are records, replaces it with one column per named field. Optional rename list resolves name collisions with existing columns.
**PySpark equivalent:**
```python
# Simple flatten — all fields of the struct become top-level columns:
df_flat = df.select("*", F.col("rec.*")).drop("rec")

# Equivalent with explicit field list and renames (mirrors M's newColumnNames):
df_flat = df.select(
    "*",
    F.col("rec.aa").alias("aa"),
    F.col("rec.bb").alias("bb"),
    F.col("rec.cc").alias("cc"),
).drop("rec")
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.select.html (dot-and-star nested-field access is core DataFrame syntax)
**Severity:** **Low** — mechanical, one line for the common case.
**Gotchas:**
- The dot-star form (`F.col("rec.*")`) drops the parent name; if two structs both have a `name` field you get an ambiguous-column error. Use the explicit alias form to match M's `newColumnNames` exactly.
- M record columns map to PySpark `StructType`. If the source column is actually a `MapType` (JSON loaded as a map), the equivalent is `F.col("rec").getItem("aa").alias("aa")`, not `rec.aa`.
- `Table.ExpandRecordColumn` preserves M record-field ordering; PySpark `select("*", "rec.*")` puts the struct fields at the end. Reorder downstream if column order is load-bearing.

### 3. Table.PromoteHeaders

**M reference:** https://learn.microsoft.com/powerquery-m/table-promoteheaders
**M semantics:** `Table.PromoteHeaders(table, optional options as nullable record)` — uses the first data row as column headers. With `[PromoteAllScalars=true]` it also promotes numbers/dates (otherwise only text/number).
**PySpark equivalent — two contexts:**
```python
# Context A: header is in the source file -> set the read option (preferred).
df = (
    spark.read
         .option("header", "true")
         .csv("Files/sales.csv")
)

# Context B: header is the first row of an already-loaded DataFrame (post-load promotion).
first_row = df.first()
new_cols  = [str(first_row[c]) if first_row[c] is not None else c for c in df.columns]
df = df.filter(F.row_number().over(Window.orderBy(F.monotonically_increasing_id())) > 1).toDF(*new_cols)
```
**PySpark reference:** https://spark.apache.org/docs/latest/sql-data-sources-csv.html (header option) and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.toDF.html
**Severity:** **Medium** — context A is trivial; context B (post-load) is multi-step and easy to get subtly wrong (must drop the same first row and rename — order matters).
**Gotchas:**
- 95% of `Table.PromoteHeaders` usages immediately follow a connector step — emit context A and recommend deleting the now-redundant explicit promote step.
- Context B requires sorting by an inserted row index *before* `.first()` because Spark DataFrames are unordered. Without `monotonically_increasing_id` + `Window.orderBy`, you can promote a different row each run.
- Spark column names cannot contain `.` `,` `;` `{` `}` `(` `)` `\n` `\t` `=` ` ` — sanitize the promoted names or wrap them in backticks downstream. M is happy with `#"Column With Spaces"`; PySpark is not.
- `PromoteAllScalars=true` is rarely meaningful in Spark (column names are always strings); cast with `str(...)` and move on.

### 4. Text.BetweenDelimiters

**M reference:** https://learn.microsoft.com/powerquery-m/text-betweendelimiters
**M semantics:** `Text.BetweenDelimiters(text, startDelimiter, endDelimiter, optional startIndex, optional endIndex)` — returns the substring between the start and end delimiters. Optional indices select the Nth occurrence and direction (`RelativePosition.FromEnd`).
**PySpark equivalent:**
```python
import re

# Common case: between literal "(" and ")", first occurrence.
df = df.withColumn(
    "between",
    F.regexp_extract(F.col("raw"), r"\((.*?)\)", 1),
)

# General helper for arbitrary delimiters (escape regex metachars):
def between_delimiters(col, start, end):
    pat = re.escape(start) + r"(.*?)" + re.escape(end)
    return F.regexp_extract(col, pat, 1)
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.regexp_extract.html
**Severity:** **Medium** — one-line for the simple case but human review needed for: (a) any non-default `startIndex`/`endIndex` (no clean Spark equivalent — needs `regexp_extract_all` + index); (b) `RelativePosition.FromEnd` requires reverse-then-extract.
**Gotchas:**
- M delimiters are literal; PySpark `regexp_extract` interprets them as regex. ALWAYS `re.escape` the delimiter strings.
- Use the lazy quantifier `(.*?)` to match M's "first end-delimiter after the start", not greedy `(.*)`.
- `regexp_extract` returns empty string `""` on no match; M `Text.BetweenDelimiters` returns `null`. Wrap with `F.when(F.length(...) > 0, ...).otherwise(F.lit(None))` if null-vs-empty matters downstream.

### 5. Table.ReplaceErrorValues

**M reference:** https://learn.microsoft.com/powerquery-m/table-replaceerrorvalues
**M semantics:** `Table.ReplaceErrorValues(table, errorReplacement)` — substitutes a fixed value for M *error values* (cells where evaluation raised an error, e.g. failed type cast, division by zero). The replacement spec is `{{col, value}, ...}`.
**PySpark equivalent — there is no exact analogue. M errors most often originate at type conversion, so the right pattern is "safe-cast and fillna":**
```python
# Common case: M raised errors during Number.FromText / Date.From conversions.
# Convert in PySpark with a permissive cast that returns NULL on failure, then fillna.
df = (
    df.withColumn("sales", F.col("sales").cast("double"))   # bad strings -> NULL (no exception in Spark)
      .fillna({"sales": 0})                                  # the M "errorReplacement"
)

# Alternative for already-NULL/sentinel cells:
df = df.replace(["#REF!", "#VALUE!", "#N/A", "NA"], None).fillna({"sales": 0})
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.fillna.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.replace.html
**Severity:** **High** — *no direct equivalent*. M's "error" is a typed value; Spark either coerces silently to NULL, throws an exception, or (in ANSI mode) errors the whole job. The converted code must pick a strategy. Human review required.
**Gotchas:**
- Spark `cast("int")` on `"abc"` returns NULL in legacy mode but **throws** in ANSI mode (`spark.sql.ansi.enabled=true`, default in newer Spark). If the source dataflow relied on the silent-conversion-to-error behavior, the converted notebook may now fail loudly — flag for review.
- If the M dataflow used `try ... otherwise ...`, the equivalent is `F.coalesce(F.try_cast(col, type), default)` (Spark 3.5+).
- Excel sentinel strings (`#REF!`, `#VALUE!`, `#N/A`) are NOT M errors but string values that M *then* failed to cast — handle them with `.replace([...], None)` *before* the cast.
- Per-column replacement maps from M (`{{"A","hello"},{"B","world"}}`) translate cleanly to `df.fillna({"A":"hello","B":"world"})`.

### 6. Table.TransformColumnNames

**M reference:** https://learn.microsoft.com/powerquery-m/table-transformcolumnnames
**M semantics:** `Table.TransformColumnNames(table, nameGenerator as function, optional options)` — applies `nameGenerator(name)` to every column name. Options: `MaxLength`, `Comparer` (for deduping case-insensitively).
**PySpark equivalent:**
```python
# Common: apply a python lambda to every column name.
df = df.toDF(*[name_fn(c) for c in df.columns])

# Example: lowercase + strip whitespace (a typical conversion):
df = df.toDF(*[c.strip().lower().replace(" ", "_") for c in df.columns])
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.toDF.html
**Severity:** **Low** — one line.
**Gotchas:**
- `toDF(*names)` requires the new list length to equal `len(df.columns)` exactly; the lambda must always return a string (no `None`).
- M's `MaxLength` truncation + dedup is non-trivial to replicate. Emit `[name_fn(c)[:max_len] for c in df.columns]` and *then* check for duplicates with `len(set(...)) == len(...)`; raise if not. Do not silently dedup.
- Avoid the anti-pattern of chaining `withColumnRenamed` N times — it builds an O(N²) logical plan. Use `toDF` or a single `select(*aliased_cols)`.

### 7. Text.From

**M reference:** https://learn.microsoft.com/powerquery-m/text-from
**M semantics:** `Text.From(value as any, optional culture as nullable text)` — universal "to text" cast. Accepts number, date, time, datetime, datetimezone, logical, duration, binary. Returns `null` for `null` input. Optional culture for locale-specific date/number formatting.
**PySpark equivalent:**
```python
# Default culture (en-US-ish, ISO for dates):
df = df.withColumn("s", F.col("v").cast("string"))

# Culture-aware date formatting (use date_format / format_number instead of plain cast):
df = df.withColumn("s_de", F.date_format(F.col("v"), "dd.MM.yyyy HH:mm:ss"))
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.Column.cast.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.date_format.html
**Severity:** **Low** — one-line cast for the default case.
**Gotchas:**
- `cast("string")` on a date in PySpark yields ISO format (`2024-06-24`), NOT the M default (`6/24/2024 2:32:22 PM`). If downstream pipelines parse the string back, the formats won't match — use `F.date_format(col, "M/d/yyyy h:mm:ss a")` to mimic M's en-US default.
- The optional `culture` argument requires `date_format` / `format_number`, not `cast`. If the source dataflow passed a culture, mark for human review.
- `Text.From(null) -> null` — PySpark `cast` preserves NULL the same way, no extra handling needed.
- `Text.From(true) -> "TRUE"`, but `cast("string")` on a Spark boolean yields `"true"` (lowercase). If the downstream pipeline does literal `== "TRUE"` comparisons, force `F.upper(F.col("b").cast("string"))`.

### 8. Text.Lower

**M reference:** https://learn.microsoft.com/powerquery-m/text-lower
**M semantics:** `Text.Lower(text as nullable text, optional culture as nullable text)` — lowercases. Returns null for null input.
**PySpark equivalent:**
```python
df = df.withColumn("lower_name", F.lower(F.col("name")))
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.lower.html
**Severity:** **Low** — one-line, exact equivalent.
**Gotchas:**
- `F.lower` is locale-insensitive (UTF-16 simple case folding). M's optional `culture` arg enables Turkic dotless-I handling (`İ -> i`); Spark doesn't. Almost never matters but flag if culture was explicitly passed.
- NULL handling matches M (`F.lower(NULL) -> NULL`).

### 9. Text.Trim

**M reference:** https://learn.microsoft.com/powerquery-m/text-trim
**M semantics:** `Text.Trim(text as nullable text, optional trim as any)` — strips leading and trailing whitespace by default; optional `trim` argument can be a single char or list of chars to strip instead.
**PySpark equivalent:**
```python
# Default whitespace trim:
df = df.withColumn("clean", F.trim(F.col("raw")))

# Custom trim characters (Spark 3.5+):
df = df.withColumn("clean", F.btrim(F.col("raw"), F.lit("0/<>")))
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.trim.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.btrim.html
**Severity:** **Low** for the default whitespace case; **Medium** if custom trim chars are passed (need `btrim` / `regexp_replace` fallback on pre-3.5 Spark).
**Gotchas:**
- `F.trim` only strips ASCII whitespace + a few Unicode spaces. M strips all Unicode whitespace. For high-fidelity Unicode trim use `F.regexp_replace(col, r"^\s+|\s+$", "")`.
- For the `trim` arg as a list-of-chars (e.g. `Text.Trim(x, {"<", ">", "/"})`), `F.btrim` (Spark 3.5+) takes a single string of all chars to strip: `F.btrim(col, F.lit("<>/"))`. On pre-3.5 emit `F.regexp_replace(col, r"^[<>/]+|[<>/]+$", "")`.

### 10. List.RemoveNulls

**M reference:** https://learn.microsoft.com/powerquery-m/list-removenulls
**M semantics:** `List.RemoveNulls(list as list) as list` — drops every `null` from a list.
**PySpark equivalent — two contexts:**
```python
# Context A: list as a DataFrame column rows (List.RemoveNulls on a Table.Column-style list).
df_clean = df.dropna(subset=["value"])  # drops rows where value is NULL

# Context B: list as an array column (each row has an array; remove nulls within each array).
df = df.withColumn("arr_clean", F.filter(F.col("arr"), lambda x: x.isNotNull()))

# Context C: literal python list, M list was a hardcoded list.
clean = [x for x in lst if x is not None]
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.dropna.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.filter.html
**Severity:** **Low** in each individual context, but context detection (column vs array vs literal) is required — that's the value-add.
**Gotchas:**
- Most common M usage is `List.RemoveNulls(Table.Column(t, "x"))` — the converter should usually emit context A (`dropna(subset=[...])`), NOT context B.
- `F.filter` with a lambda is Spark 3.1+. On earlier versions use `F.expr("filter(arr, x -> x is not null)")`.

### 11. List.Distinct

**M reference:** https://learn.microsoft.com/powerquery-m/list-distinct
**M semantics:** `List.Distinct(list, optional equationCriteria)` — returns distinct values, preserving first occurrence. Optional comparer for case-insensitive / culture-aware equality.
**PySpark equivalent — two contexts:**
```python
# Context A: distinct rows / column values (most common M usage).
df_distinct = df.dropDuplicates(["value"])  # NOT df.distinct() unless ALL columns matter

# Context B: distinct elements within an array column.
df = df.withColumn("arr_d", F.array_distinct(F.col("arr")))

# Context C: literal list -> use dict.fromkeys to preserve order (Python 3.7+).
distinct = list(dict.fromkeys(lst))
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.array_distinct.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.dropDuplicates.html
**Severity:** **Low** per context; **Medium** overall because case-insensitive / comparer arg requires extra code.
**Gotchas:**
- `df.distinct()` deduplicates *all columns together* — almost never what `List.Distinct(Table.Column(t,"x"))` means. Use `dropDuplicates(["x"])`.
- M `List.Distinct(lst, Comparer.OrdinalIgnoreCase)` — emit `df.dropDuplicates([F.lower(F.col("x")).alias("__k")])` semantics (i.e. dedup on a derived key), OR document the case-folding step explicitly.
- `array_distinct` does NOT preserve original order in older Spark versions; Spark 3.5+ docs say order-preserving. Flag for cross-version safety.

### 12. List.Count

**M reference:** https://learn.microsoft.com/powerquery-m/list-count
**M semantics:** `List.Count(list as list) as number` — returns the count of items in a list.
**PySpark equivalent — context matters more here than anywhere else in the catalog:**
```python
# Context A: M was counting rows (Table.RowCount-like, e.g. List.Count(Table.Column(t,"x"))).
n = df.count()                          # scalar
df = df.agg(F.count("*").alias("n"))    # as a single-row DataFrame

# Context B: M was counting elements per row in an array column.
df = df.withColumn("n_items", F.size(F.col("arr")))

# Context C: hardcoded literal list in M.
n = len(lst)
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.size.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.count.html
**Severity:** **Medium** — choosing between `count()` (action, triggers job) and `size()` (column expression) is critical and context-dependent.
**Gotchas:**
- `df.count()` is an *action* — triggers a full job, can be expensive. If the value is only needed inside another expression, use `F.count("*").over(...)` or a broadcast variable.
- `F.size(null_array)` returns `-1` (Spark legacy) or `null` (with `spark.sql.legacy.sizeOfNull=false`). M `List.Count(null)` errors. Add `F.when(col.isNull(), 0).otherwise(F.size(col))` for safety.
- `F.size` works on both arrays and maps; the result for a map is the number of key-value pairs.

### 13. List.Transform

**M reference:** https://learn.microsoft.com/powerquery-m/list-transform
**M semantics:** `List.Transform(list, transform as function)` — maps a function over each list element, returning a new list of equal length.
**PySpark equivalent — context matters:**
```python
# Context A: literal list, M used a literal lambda.
result = [fn(x) for x in lst]

# Context B: array column, apply a function to each element.
df = df.withColumn("arr2", F.transform(F.col("arr"), lambda x: x + 1))

# Context C: column-of-rows (most common — M used List.Transform to apply to a Table.Column).
df = df.withColumn("col2", fn(F.col("col")))     # vectorized — preferred
# Last-resort UDF (slow, avoid):
my_udf = F.udf(fn, returnType=StringType())
df = df.withColumn("col2", my_udf(F.col("col")))
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.transform.html
**Severity:** **Medium** — multi-context; context C should default to native column expressions, NOT UDFs, but the converter has to recognize what `fn` does and rewrite to Spark SQL builtins.
**Gotchas:**
- `F.transform` lambda receives a `Column` argument — your transform must use `F.*` functions, not python-level operations.
- Do NOT default to UDFs for context C — they break Catalyst optimization and run in Python. Prefer a native `F.*` rewrite (e.g., M `List.Transform(col, each Text.Lower(_))` → `F.lower(col)`).
- M can `List.Transform` over heterogeneous lists; PySpark `F.transform` requires a typed array. Flag any case where the source list mixes types.

### 14. List.AnyTrue

**M reference:** https://learn.microsoft.com/powerquery-m/list-anytrue (see list-functions index)
**M semantics:** `List.AnyTrue(list)` — returns `true` if any boolean element in the list is `true`.
**PySpark equivalent — three contexts:**
```python
# Context A: literal list of booleans.
result = any(lst)

# Context B: array column of booleans.
df = df.withColumn("any_true", F.exists(F.col("flags"), lambda x: x))
# Equivalent shorthand:
df = df.withColumn("any_true", F.array_contains(F.col("flags"), True))

# Context C: aggregation across rows ("does any row in column flag = true?").
df.select(F.max(F.col("flag").cast("int")).alias("any_true"))   # 1 if any TRUE, 0 if none

# Context D (often what M meant): List.AnyTrue({condition over each row}) → use F.exists on collected list,
#   but the idiomatic Spark form is a boolean filter:
n = df.filter(F.col("flag") == True).limit(1).count() > 0
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.exists.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.array_contains.html
**Severity:** **Medium** — needs context detection.
**Gotchas:**
- `F.array_contains(arr, True)` is the easy version, but returns NULL if the array contains NULL. `F.exists(arr, lambda x: x)` ignores NULLs, matching M.
- Context D (`List.AnyTrue` used as a row-level early-exit on a table query) commonly degenerates to `df.filter(...).limit(1).count() > 0` — which is still a Spark job. Prefer pushing the boolean check upstream if possible.
- `F.exists` lambda — same constraints as `F.transform`: must use `F.*` Column ops, not python `if`.

### 15. Text.Combine (with separator)

**M reference:** https://learn.microsoft.com/powerquery-m/text-combine
**M semantics:** `Text.Combine(texts as list, optional separator as nullable text)` — joins all text values with the separator. Null elements are *ignored* (skipped, not inserted as empty).
**PySpark equivalent:**
```python
# Combining columns with a separator — USE concat_ws (NOT concat).
df = df.withColumn("full", F.concat_ws(" | ", F.col("city"), F.col("state"), F.col("zip")))

# Combining elements of an array column with a separator:
df = df.withColumn("joined", F.array_join(F.col("arr"), " | "))

# Literal list of strings in M -> python:
s = " | ".join([x for x in lst if x is not None])
```
**PySpark reference:** https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.concat_ws.html and https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.array_join.html
**Severity:** **Low** — one-line.
**Gotchas:**
- ALWAYS use `F.concat_ws(sep, ...)`, NEVER `F.concat(...)`: `F.concat` has no separator and propagates NULL (`F.concat("a", NULL) -> NULL`). `F.concat_ws` treats NULLs as empty strings, matching M's "nulls are ignored" semantics most closely.
- For an *array column* the right function is `F.array_join(arr, sep)`, not `F.concat_ws` (which takes a varargs of columns, not an array).
- M ignores nulls entirely (so `Text.Combine({"a", null, "b"}, ",")` → `"a,b"`). `F.concat_ws` produces `"a,,b"` (empty between the separators) when given separate columns where one is NULL. If exact M parity matters, filter nulls first with `F.array_compact` (Spark 3.4+) before `F.array_join`.
- The signature in the task description (`Text.Combine(list, " | ")`) is the array form — emit `F.array_join`, not `F.concat_ws`, when the M argument is a list expression rather than separate fields.

---

## Open questions / unresolved patterns

1. **SharePoint.Files exact code-gen.** OneLake shortcuts are an admin / UI step, not a notebook command. The catalog entry should *describe* the migration (create shortcut, then read) and emit a `# TODO:` placeholder rather than executable code. There is no Microsoft-supported pure-PySpark equivalent that reproduces the M behavior without a Fabric admin action. (Sources: Fabric blog + create-onedrive-sharepoint-shortcut doc — see Pattern 1.)

2. **Table.ReplaceErrorValues** — Spark and M have fundamentally different error models (M errors are first-class values; Spark has NULL + exceptions). The "right" PySpark replacement depends on what *raised* the M error: type conversion, division-by-zero, or upstream connector. We picked the most common (safe-cast + fillna) but the catalog entry should flag this as a Severity-High pattern that always benefits from human review.

3. **`PromoteAllScalars=true` exact semantics.** M promotes non-text scalars by stringifying them with the supplied `Culture`. The equivalent `str(...)` in PySpark uses Python's default repr which differs from M's en-US default for dates/numbers. If a dataflow depends on the exact promoted column name (e.g. for downstream `df.select("1/1/1980")`), the converted code may need `date_format(..., "M/d/yyyy")` before stringification. Catalog entry should note this without trying to handle it generically.

4. **List.Count / List.Transform / List.AnyTrue context detection.** The catalog can list the three contexts (literal / array column / row aggregate) but the *converter agent* still has to inspect the M call site to pick one. The catalog cannot encode that decision — it must instruct the agent to look at the binding of the `list` argument.

5. **`Text.Trim` with list-of-chars on pre-Spark-3.5.** `F.btrim` was added in 3.5. The catalog should emit the `regexp_replace` fallback as a comment so users on older Spark versions (e.g. Fabric runtime 1.2 prior to its 3.5 upgrade) aren't blocked. Confirm Fabric's current Spark version before committing to `btrim` as the primary recommendation.

6. **`array_distinct` order-preservation.** Older Spark releases do not guarantee element order. We could not find a definitive "since version N, order is preserved" statement in the official docs — only behavioural reports. If preserve-order is load-bearing, the catalog should recommend the explicit pattern `df.withColumn("arr_d", F.expr("transform(arr, x -> x) /* and dedupe */"))` or a UDF. Flag for follow-up verification.
