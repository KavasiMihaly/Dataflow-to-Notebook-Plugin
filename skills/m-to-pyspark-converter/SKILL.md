---
name: m-to-pyspark-converter
description: Convert Power Query M code from PBIP semantic models (TMDL) to Fabric notebooks — PySpark (default) or single-node Python (polars + delta-rs) via `--target python`. Extracts M expressions from partition definitions in .tmdl table files, parses transformations, and generates equivalent code for the chosen engine. Use when migrating Power BI models to Fabric notebooks, converting dataflow logic to PySpark or polars, or translating M expressions. Accepts TMDL folders, .tmdl files, or raw M code.
allowed-tools: Read Write Edit Glob Grep
paths: "**/*.tmdl, **/*.pq"
---

# M-to-Notebook Converter (PySpark or Python)

Convert Power Query M code from PBIP semantic models (TMDL format) to Microsoft Fabric notebooks. Two code-gen targets share one M parser:

- `--target pyspark` (default) — Spark notebooks (`spark.read`, `F.*`, `saveAsTable`).
- `--target python` — single-node Python notebooks (`polars` + `delta-rs`), for the Fabric Python-notebook runtime.

> The skill name is kept as `m-to-pyspark-converter` for compatibility; it now emits both engines.

## Overview

Many organizations have existing Power Query M code in Power BI semantic models that needs to be migrated to Fabric notebooks. This skill automates the conversion by:

1. **Extracting** M code from `partition = m` blocks in `.tmdl` files
2. **Parsing** M let/in expressions into a structured intermediate representation
3. **Generating** equivalent code for the selected engine following Fabric notebook conventions

The converter handles the 20+ most common M transformation functions and produces clean, readable code with original M code preserved as comments for review. The same parse drives both emitters; only the emitter (PySpark vs polars) is engine-specific.

## Prerequisites

- Python 3.9+
- No external dependencies (stdlib only)
- Input: PBIP semantic model with `.tmdl` files containing `partition = m` blocks

## Usage

### Convert all tables in a semantic model

```bash
python scripts/convert_m_to_pyspark.py --tmdl-path "path/to/Model.SemanticModel/definition"
```

### Convert a single .tmdl file

```bash
python scripts/convert_m_to_pyspark.py --tmdl-file "path/to/tables/Sales.tmdl"
```

### Convert raw M code from a file

```bash
python scripts/convert_m_to_pyspark.py --m-file "query.m"
```

### Convert M code from a string

```bash
python scripts/convert_m_to_pyspark.py --m-code "let Source = Sql.Database(\"srv\", \"db\") in Source"
```

### List tables without converting

```bash
python scripts/convert_m_to_pyspark.py --tmdl-path "path/to/definition" --list-tables
```

### Specify output directory

```bash
python scripts/convert_m_to_pyspark.py --tmdl-path "path" --output-dir "3 - Notebooks/bronze/"
```

### Verbose mode

```bash
python scripts/convert_m_to_pyspark.py --tmdl-path "path" --verbose
```

### Choose the engine target

```bash
python scripts/convert_m_to_pyspark.py --tmdl-path "path" --target python
```

`--target pyspark` (the default) is unchanged. `--target python` emits single-node
polars + delta-rs. An unknown target exits non-zero with a clear error.

## M-to-Python (polars) Mapping Reference

Emitted with `--target python`. Source of truth: the research §4 translation table.

### Table Operations

| M Function | polars Equivalent |
|-----------|-------------------|
| `Table.SelectRows(t, each ...)` | `df.filter(...)` |
| `Table.AddColumn(t, "name", each ...)` | `df.with_columns((...).alias("name"))` |
| `Table.RenameColumns(t, {{"old","new"}})` | `df.rename({"old": "new"})` |
| `Table.RemoveColumns(t, {"col"})` | `df.drop("col")` |
| `Table.SelectColumns(t, {"col"})` | `df.select("col")` |
| `Table.TransformColumnTypes(t, {{"col", type}})` | `df.with_columns(pl.col("col").cast(...))` |
| `Table.Sort(t, {{"col", Order.Descending}})` | `df.sort("col", descending=True)` |
| `Table.Group(t, {"grp"}, {{"agg", each List.Sum([c])}})` | `df.group_by("grp").agg(pl.col("c").sum().alias("agg"))` |
| `Table.NestedJoin(...)` + `Table.ExpandTableColumn(...)` | `df.join(df_right, on=..., how=...)` |
| `Table.Distinct(t)` | `df.unique()` |
| `Table.Combine({t1, t2})` | `pl.concat([df, df2], how="diagonal_relaxed")` |
| `Table.ReplaceValue(t, old, new, ...)` | `df.with_columns(pl.col(c).str.replace_all/ fill_null / when-then)` |
| `Table.FillDown(t, {"col"})` | `df.with_columns(pl.col("col").forward_fill())` |
| `Table.Pivot(...)` | `df.pivot(..., aggregate_function="first")` |
| `Table.Unpivot(...)` | `df.unpivot(on=[...], variable_name=..., value_name=...)` |
| `Table.FirstN(t, n)` | `df.head(n)` |
| `Table.Buffer(t)` | no-op (polars is eager) |
| `Table.DuplicateColumn(t, "src", "new")` | `df.with_columns(pl.col("src").alias("new"))` |

### Data Types

| M Type | polars Type |
|--------|-------------|
| `type text` | `pl.Utf8` |
| `type number` | `pl.Float64` |
| `Int64.Type` | `pl.Int64` |
| `Int32.Type` | `pl.Int32` |
| `type date` | `pl.Date` |
| `type datetime` | `pl.Datetime` |
| `type logical` | `pl.Boolean` |
| `Decimal.Type` | `pl.Decimal(38, 18)` |
| `Currency.Type` | `pl.Decimal(19, 4)` |

### Join Types

| M Join Kind | polars `how` |
|------------|--------------|
| `JoinKind.LeftOuter` | `"left"` |
| `JoinKind.Inner` | `"inner"` |
| `JoinKind.RightOuter` | `"right"` |
| `JoinKind.FullOuter` | `"full"` |
| `JoinKind.LeftAnti` | `"anti"` |

`JoinKind.RightAnti` has no direct polars `how`; it degrades to `"anti"` with a review TODO.

### Expression Patterns

| M Pattern | polars Equivalent |
|-----------|-------------------|
| `each [Column]` | `pl.col("Column")` |
| `each [Col] = "value"` | `pl.col("Col") == "value"` |
| `each if [X] then Y else Z` | `pl.when(...).then(Y).otherwise(Z)` |
| `each [A] & [B]` | `pl.concat_str([pl.col("A"), pl.col("B")])` |
| `Text.Upper([Col])` | `pl.col("Col").str.to_uppercase()` |
| `Text.Contains([Col], "x")` | `pl.col("Col").str.contains("x", literal=True)` |

### Write idiom

```python
write_deltalake(table_path(target_table), df.to_arrow(),
                mode="overwrite", schema_mode="overwrite")
```

Reads/writes go through a `table_path()` resolver (provided by the Python utilities
notebook) so the schema-enabled-vs-classic lakehouse path is handled in one place.

## M-to-PySpark Mapping Reference

### Table Operations

| M Function | PySpark Equivalent |
|-----------|-------------------|
| `Table.SelectRows(t, each ...)` | `df.filter(...)` |
| `Table.AddColumn(t, "name", each ...)` | `df.withColumn("name", ...)` |
| `Table.RenameColumns(t, {{"old", "new"}})` | `df.withColumnRenamed("old", "new")` |
| `Table.RemoveColumns(t, {"col"})` | `df.drop("col")` |
| `Table.SelectColumns(t, {"col"})` | `df.select("col")` |
| `Table.TransformColumnTypes(t, {{"col", type}})` | `df.withColumn("col", F.col("col").cast(...))` |
| `Table.Sort(t, {{"col", Order.Ascending}})` | `df.orderBy(F.col("col").asc())` |
| `Table.Group(t, {"grp"}, {{"agg", each ...}})` | `df.groupBy("grp").agg(...)` |
| `Table.NestedJoin(...)` + `Table.ExpandTableColumn(...)` | `df.join(df_right, ..., "left")` |
| `Table.Distinct(t)` | `df.distinct()` |
| `Table.Combine({t1, t2})` | `df.unionByName(df2)` |
| `Table.ReplaceValue(t, old, new, ...)` | `df.withColumn(..., F.when(...).otherwise(...))` |
| `Table.FillDown(t, {"col"})` | Window function with `F.last(ignorenulls=True)` |
| `Table.Pivot(...)` | `df.groupBy().pivot().agg()` |
| `Table.Unpivot(...)` | `df.unpivot(...)` |
| `Table.FirstN(t, n)` | `df.limit(n)` |
| `Table.Buffer(t)` | `df.cache()` |
| `Table.DuplicateColumn(t, "src", "new")` | `df.withColumn("new", F.col("src"))` |

### Data Types

| M Type | PySpark Type |
|--------|-------------|
| `type text` | `StringType()` |
| `type number` | `DoubleType()` |
| `Int64.Type` | `LongType()` |
| `Int32.Type` | `IntegerType()` |
| `type date` | `DateType()` |
| `type datetime` | `TimestampType()` |
| `type logical` | `BooleanType()` |
| `Decimal.Type` | `DecimalType(38, 18)` |
| `Currency.Type` | `DecimalType(19, 4)` |

### Join Types

| M Join Kind | PySpark `how` |
|------------|---------------|
| `JoinKind.LeftOuter` | `"left"` |
| `JoinKind.Inner` | `"inner"` |
| `JoinKind.RightOuter` | `"right"` |
| `JoinKind.FullOuter` | `"outer"` |
| `JoinKind.LeftAnti` | `"left_anti"` |

### Expression Patterns

| M Pattern | PySpark Equivalent |
|-----------|-------------------|
| `each [Column]` | `F.col("Column")` |
| `each [Col] = "value"` | `F.col("Col") == "value"` |
| `each if [X] then Y else Z` | `F.when(F.col("X"), Y).otherwise(Z)` |
| `each [A] & [B]` | `F.concat(F.col("A"), F.col("B"))` |
| `#"Quoted Name"` | `F.col("Quoted Name")` |
| `Text.Upper([Col])` | `F.upper(F.col("Col"))` |
| `Text.Contains([Col], "x")` | `F.col("Col").contains("x")` |

## Limitations

- **Complex M expressions**: Deeply nested `let/in`, custom functions, and `#section` references produce TODO markers
- **Data sources**: SQL Server, CSV, Excel connections are replaced with `spark.read.table()` placeholders
- **Credentials**: All connection strings and credentials are stripped - output uses Fabric lakehouse patterns
- **Custom M functions**: User-defined M functions are not resolved; they appear as TODO comments
- **Record/list operations**: Complex `Record.*` and `List.*` operations beyond aggregations need manual conversion
- **Error handling**: M `try/otherwise` blocks are not converted
- **Table.TransformColumns**: Complex column transformations are preserved as TODO comments

## Integration with Agents

### With fabric-bronze-builder
The converter output serves as a starting point for the fabric-bronze-builder agent. The agent can refine the generated PySpark to match project-specific patterns (lakehouse paths, naming conventions, error handling).

### With business-analyst
When gathering requirements for Fabric migration, the business-analyst agent can use `--list-tables` to inventory existing Power Query transformations and identify complexity.

### With fabric-project-setup
After initializing a Fabric project, run the converter to bootstrap bronze notebooks from existing semantic model logic.

## Troubleshooting

### No partitions found
- Ensure the `--tmdl-path` points to the `definition` folder (or its parent)
- Check that `.tmdl` files contain `partition ... = m` blocks
- DirectQuery partitions without M code are skipped

### Steps marked as TODO
- Unknown M functions are preserved as comments with original code
- Review and manually convert these steps
- Common TODOs: custom M functions, complex `each` expressions, `try/otherwise`

### Output doesn't compile
- The generated code is a starting point - Fabric-specific imports and connections need configuration
- Replace `spark.read.table(source_table)` with actual lakehouse table references
- Verify column names match your data (M may have renamed them)
