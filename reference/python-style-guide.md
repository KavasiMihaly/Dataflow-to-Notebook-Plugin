# Python notebook style guide (polars / duckdb / delta-rs)

**Engine:** `python` (Fabric single-node 2-vCore / 16 GB jupyter kernel).
This is the engine-specific counterpart to `pyspark-style-guide.md`. When
`engine=python`, builders read **this** guide, not the PySpark one.

There is **no Spark session** in a Python notebook: no `spark` object, no
`pyspark.sql.functions`, no `delta.tables.DeltaTable`. Every generated line uses
the polars / duckdb / delta-rs idiom instead.

## Imports (the only ones you need)

```python
import polars as pl
from datetime import datetime, timezone
from deltalake import write_deltalake, DeltaTable
import notebookutils  # secrets, run context, session
# import duckdb        # only when a set-based SQL-style transform is clearer
```

**Never** `from pyspark.sql import functions as F` and **never** use the `F.`
prefix. There is no `F` in a Python notebook.

## OOM-safe defaults — prefer polars / duckdb, NOT pandas

The runtime is single-node (~1 GB comfortable, multi-GB risky). Fabric's own
guidance: *"If you encounter OOM when loading large volume of data, try using
DuckDB, Polars or PyArrow dataframe instead of pandas."*

- **Default DataFrame engine = polars.** Use `pl.read_*` / `pl.DataFrame`.
- Use **lazy** polars (`pl.scan_*` + `.collect()`) for large reads so the engine
  streams/optimizes rather than materializing eagerly.
- Reach for **duckdb** when a transform is naturally set-based SQL
  (`duckdb.sql("SELECT ... FROM delta_scan('...')")`).
- Avoid **pandas** as the working engine. Only touch pandas at the very edge for
  a library that demands it, and convert via Arrow (`df.to_arrow()`), never as
  the pipeline's main dataframe.

## File I/O — use the `/lakehouse/default/...` MOUNT, NOT `notebookutils.fs.ls`

> **Hard rule (research §3.3, live-confirmed 2026-06-07).** In a **pure Python
> notebook**, enumerate / list lakehouse files through the **FUSE mount**
> (`/lakehouse/default/Files/...`) using `os` / `glob` / `pathlib` — **not**
> `notebookutils.fs.ls(...)` on an `abfss://` path.

Why: `os.walk("/lakehouse/default/Files/crimedata")` returned immediately, but
`notebookutils.fs.ls("abfss://…/Files/crimedata")` **hung ~90 s then threw**
`HttpResponseError: InternalServerError` (a 500 from the OneLake DFS endpoint the
SDK fails to parse). The mount bypasses that flaky DFS endpoint.

```python
# CORRECT — list source files via the mount
import os
root = "/lakehouse/default/Files/crimedata"
files = [
    os.path.join(dp, name)
    for dp, _dirs, names in os.walk(root)
    for name in names
    if name.endswith(".csv")
]

# AVOID in pure Python notebooks — flaky DFS endpoint
# notebookutils.fs.ls("abfss://…/Files/crimedata")   # hangs ~90s then 500s
```

Reserve `notebookutils.fs` for cross-lakehouse cases where **no mount exists**,
and even then wrap it in retry / try-except.

**Scope note:** this is about *file enumeration*. **Delta-table reads** via
`pl.read_delta` / `pl.scan_delta` / `deltalake.DeltaTable` use OneLake directly
and are **unaffected** — keep using them for tables.

## Transform idioms (PySpark → polars)

| Operation | PySpark (do not use) | polars (use) |
|---|---|---|
| Add column | `df.withColumn("c", …)` | `df.with_columns(pl.lit(...).alias("c"))` |
| Rename | `df.withColumnRenamed("a","b")` | `df.rename({"a": "b"})` |
| Cast | `F.col("x").cast("decimal(18,2)")` | `pl.col("x").cast(pl.Decimal(18, 2))` |
| Filter | `df.filter(F.col("x") > 0)` | `df.filter(pl.col("x") > 0)` |
| Dedup latest | `Window…row_number()==1` | `df.sort("_load_timestamp", descending=True).unique(subset=[...], keep="first")` |
| Decode / case | `F.when(...).otherwise(...)` | `pl.when(...).then(...).otherwise(...)` |
| Unpivot | `df.unpivot` / `stack(...)` | `df.unpivot(index=[...], on=[...], variable_name=..., value_name=...)` |
| Join | `df.join(r, on, "left")` | `df.join(r, on=..., how="left")` |

## Metadata columns

- `_load_timestamp` → `pl.lit(datetime.now(timezone.utc)).alias("_load_timestamp")`
  (a literal column — there is no per-row `current_timestamp()` UDF needed).
- `_source_file` → the **source path literal**, typed:
  `pl.lit(source_file, dtype=pl.Utf8).alias("_source_file")` (single-node has no
  per-row `input_file_name()`; pass the resolved file path string).
- `_load_id` → coerce the run id, then type the literal:
  ```python
  load_id = notebookutils.runtime.context.get("currentRunId") or "manual"
  pl.lit(load_id, dtype=pl.Utf8).alias("_load_id")
  ```

> **`dtype=pl.Utf8` on the string literals is mandatory, and use `or "manual"` —
> not a `dict.get` default.** `currentRunId` can be **present-but-None** in an
> interactive run, and `get(key, default)` only returns the default when the key
> is *absent*, so `get("currentRunId", "manual")` still yields `None`. Likewise
> `_source_file` is `None` for sources with no file path (OData / API). An
> **untyped `pl.lit(None)` produces a polars `Null` dtype → Arrow `null` type**,
> which delta-rs rejects on write: `SchemaMismatchError: Invalid data type for
> Delta Lake: Null`. Typing the literal forces a concrete `String` column even
> when the value is `None`. (PySpark is unaffected — `F.lit` + Spark writes
> tolerate it differently.)

## Secrets & connections

- Any secret → `notebookutils.credentials.getSecret(akv_name, secret_name)`.
- **Never** embed a connection string, key, or password in generated code.
- SQL-source bronze (when needed) → `notebookutils.data.connect_to_artifact(...)`
  `.query("SELECT …")` (Python-notebook-only ODBC/T-SQL), not Spark JDBC.

## Spark-only features that have NO Python equivalent

- **VORDER / NEE / Vegas cache** are Spark-only. Drop the `spark.conf.set(...vorder...)`
  guidance entirely for Python tables; a later Spark job or the SQL endpoint's
  background optimization can V-ORDER them.
- **No Environment item, no env vars, no library item.** Any non-pre-installed
  dependency is `%pip install`-ed inline in the first cell.
- Restart the kernel with `notebookutils.session.restartPython()`, not `sys.exit(0)`.

## Writes target only the bound lakehouse via `table_path()`

Never hard-code `Tables/...`. Resolve every write/read target through the
`table_path()` helper in `nb_utils_config` (see `python-delta-patterns.md`) so
the schema-enabled-vs-classic registration gotcha is handled in one place. No
local absolute paths in any generated cell — only the `/lakehouse/default/...`
mount or the lakehouse-relative path returned by `table_path()`.
