# Python Delta patterns (delta-rs / polars write_delta)

**Engine:** `python`. Counterpart to `delta-lake-patterns.md` (which is
Spark-only). When `engine=python`, builders read **this** guide.

There is no `DeltaTable.forName(...)` / `saveAsTable` here — Delta I/O goes
through **delta-rs** (`deltalake.write_deltalake` / `DeltaTable`) or polars'
`df.write_delta(...)`, all targeting the path returned by `table_path()`.

## `table_path()` — the registration resolver (own it in ONE place)

Every read/write target is resolved by `table_path()` in `nb_utils_config`, never
hard-coded. This is the single highest-risk runtime behavior of the Python path —
see the "Unidentified table" gotcha below.

```python
def table_path(name: str, schema_enabled: bool = SCHEMA_ENABLED) -> str:
    """Resolve a managed Delta table path under the default lakehouse mount.

    schema-enabled lakehouse -> /lakehouse/default/Tables/dbo/<name>
    classic lakehouse        -> /lakehouse/default/Tables/<name>
    """
    base = "/lakehouse/default/Tables"
    return f"{base}/dbo/{name}" if schema_enabled else f"{base}/{name}"
```

- **`schema_enabled` source = `project-config.yml`.** The scaffold records the
  lakehouse schema mode there (`medallion.layers.*.schema_enabled`); the utilities
  notebook reads it into the module-level `SCHEMA_ENABLED` constant. Default is
  `False` (classic lakehouse) — the safer default, since most existing lakehouses
  are classic and a classic path under a classic lakehouse always registers.
- Builders call `table_path("bronze_customers")` and never type `Tables/...`.

## The "Unidentified table" gotcha (must-handle)

When `write_deltalake` / `write_delta` writes Delta files to a managed path, the
files are valid and queryable, but the lakehouse **catalog may not register the
logical table** — it shows under an **"Unidentified"** folder. Causes & fixes:

1. **Schema-enabled lakehouse needs the schema in the path.** Write to
   `…/Tables/dbo/<table>`, not `…/Tables/<table>`. Omitting `dbo` lands it in
   "Unidentified." → handled by `table_path()` when `schema_enabled=True`.
2. **Prefer the full ABFSS path for deterministic registration** when the mount
   is ambiguous:
   `abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>.Lakehouse/Tables/dbo/<table>`.
3. **Or register with DDL after write** (last resort):
   `CREATE TABLE <t> USING DELTA LOCATION '/lakehouse/.../Tables/.../<t>'`.
4. Auto-registration happens **eventually** but **not immediately** — bad for a
   pipeline that writes bronze then reads it in silver in the **same run**. The
   bronze→silver round-trip test (Slice 4) exists specifically to catch this.

## `schema_mode` needs the rust writer (the `DELTA_WRITE_KWARGS` shim)

Any `write_deltalake(...)` call that passes `schema_mode` **must** also spread
`**DELTA_WRITE_KWARGS` (defined in `nb_utils_config`, available after
`%run nb_utils_config`). On **delta-rs < 0.18** the default *pyarrow* writer
rejects `schema_mode`:

```
ValueError: schema_mode 'merge' is not supported in pyarrow engine. Use engine=rust
```

The shim injects `engine="rust"` on those runtimes and **nothing** on delta-rs
>= 0.18 (which made rust the only writer and later removed the `engine` kwarg —
passing it there raises `TypeError`). So a hard-coded `engine="rust"` is *not*
forward-safe; always use the shim:

```python
# in nb_utils_config (owns the gotcha in ONE place):
import deltalake
def _delta_write_kwargs() -> dict:
    try:
        major, minor = (int(p) for p in deltalake.__version__.split(".")[:2])
    except Exception:
        return {}
    return {"engine": "rust"} if (major, minor) < (0, 18) else {}
DELTA_WRITE_KWARGS = _delta_write_kwargs()
```

## Bronze write — append + schema merge

Bronze is **append-only**. Schema evolution allowed (`schema_mode="merge"`).

```python
from deltalake import write_deltalake

write_deltalake(
    table_path("bronze_customers"),
    df.to_arrow(),                 # polars -> Arrow (delta-rs writes Arrow)
    mode="append",
    schema_mode="merge",           # PySpark equivalent: mergeSchema=true
    **DELTA_WRITE_KWARGS,          # rust-writer shim — REQUIRED with schema_mode
)
```

Equivalent via polars: `df.write_delta(table_path("bronze_customers"),
mode="append", delta_write_options={"schema_mode": "merge", **DELTA_WRITE_KWARGS})`.

## Silver write — overwrite + schema overwrite

Silver is a **full refresh of clean state** (overwrite, never append).

```python
write_deltalake(
    table_path("silver_customers"),
    df.to_arrow(),
    mode="overwrite",
    schema_mode="overwrite",       # PySpark equivalent: overwriteSchema=true
    **DELTA_WRITE_KWARGS,          # rust-writer shim — REQUIRED with schema_mode
)
```

## Reads (delta tables — OneLake-backed, mount-unaffected)

```python
# eager
df = pl.read_delta(table_path("bronze_customers"))
# lazy (preferred for large tables)
lf = pl.scan_delta(table_path("bronze_customers"))
# arrow / duckdb
DeltaTable(table_path("bronze_customers")).to_pyarrow_table()
```

`read_bronze("customers")` in `nb_utils_config` wraps `pl.read_delta(table_path(
"bronze_" + name))` so silver notebooks only ever say `read_bronze("customers")`.

## MERGE / upsert (delta-rs `TableMerger`)

```python
(
    DeltaTable(table_path("silver_customers"))
    .merge(
        source=df.to_arrow(),
        predicate="target.id = source.id",
        source_alias="source",
        target_alias="target",
    )
    .when_matched_update_all()
    .when_not_matched_insert_all()
    .execute()
)
```

> **delta-rs merge maturity (open micro-question, research §8.3):** if a needed
> merge feature is missing on the pinned runtime, **fall back to read-modify-
> overwrite** for small tables (read current → combine in polars → `write_deltalake
> mode="overwrite"`). Confirmed acceptable for silver's small-table case.

## Row-count validation (cheap)

Do **not** materialize the table just to count it. Prefer:

```python
DeltaTable(table_path("bronze_customers")).to_pyarrow_dataset().count_rows()
```

(or a duckdb `SELECT count(*) FROM delta_scan('...')`). `pl.read_delta(path).height`
also works but loads the whole table — avoid on large tables.

## VORDER / optimizeWrite — N/A

Spark-only. No Python equivalent; omit entirely. A later Spark job or the SQL
endpoint's background optimization can V-ORDER Python-written tables.

## No local paths

Every path in generated code is the `/lakehouse/default/...` mount or the
lakehouse-relative value from `table_path()`. Never a Windows drive path, a
Unix home path, or any user-home reference.
