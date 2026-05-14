---
name: m-to-pyspark-converter
description: Convert Power Query M code from PBIP semantic models (TMDL) to Fabric PySpark notebooks. Extracts M expressions from partition definitions in .tmdl table files, parses transformations, and generates equivalent PySpark code. Use when migrating Power BI models to Fabric notebooks, converting dataflow logic to PySpark, or translating M expressions. Accepts TMDL folders, .tmdl files, or raw M code.
allowed-tools: Read Write Edit Glob Grep
paths: "**/*.tmdl, **/*.pq"
---

# M-to-PySpark Converter

Convert Power Query M code from PBIP semantic models (TMDL format) to Microsoft Fabric PySpark notebooks.

## Overview

Many organizations have existing Power Query M code in Power BI semantic models that needs to be migrated to Fabric PySpark notebooks. This skill automates the conversion by:

1. **Extracting** M code from `partition = m` blocks in `.tmdl` files
2. **Parsing** M let/in expressions into a structured intermediate representation
3. **Generating** equivalent PySpark code following Fabric notebook conventions

The converter handles the 20+ most common M transformation functions and produces clean, readable PySpark with original M code preserved as comments for review.

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
