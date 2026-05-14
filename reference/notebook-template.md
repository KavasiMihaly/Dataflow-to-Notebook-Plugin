# Fabric Notebook Cell Structure

Standard cell layout for PySpark notebooks in the medallion architecture. All agents generating notebooks must follow this structure.

---

## Universal Cell Structure

Every notebook follows this cell order:

| Cell # | Purpose | Required | Notes |
|--------|---------|----------|-------|
| 1 | `%%configure` (optional) | No | Resource tuning. Must be first cell or triggers session restart |
| 2 | Parameters | Yes | Toggle as parameter cell in Fabric UI. Contains all configurable values |
| 3 | Imports | Yes | All `from pyspark.sql` imports using `F.` alias convention |
| 4 | Configuration / Constants | If needed | Spark config settings, derived constants |
| 5+ | Business Logic | Yes | Layer-specific processing cells |
| Final | Validation / Logging | Yes | Row counts, assertions, notebook exit value |

---

## Bronze Layer Template

```python
# Cell 1: Parameters
# (Toggle as Parameter Cell in Fabric UI)
source_name = "customers"
source_format = "csv"  # csv | parquet | json
source_path = "Files/raw/customers.csv"
load_mode = "append"  # append | overwrite (use append for bronze)
```

```python
# Cell 2: Imports
from pyspark.sql import functions as F
from pyspark.sql.types import *
```

```python
# Cell 3: Read Source Data
df_raw = spark.read.format(source_format) \
    .option("header", "true") \
    .option("inferSchema", "true") \
    .load(source_path)

print(f"Source rows: {df_raw.count()}")
print(f"Source columns: {df_raw.columns}")
```

```python
# Cell 4: Add Metadata Columns
df_bronze = df_raw \
    .withColumn("_load_timestamp", F.current_timestamp()) \
    .withColumn("_source_file", F.input_file_name()) \
    .withColumn("_load_id", F.lit(
        notebookutils.runtime.context.get("currentRunId", "manual")
    ))
```

```python
# Cell 5: Write to Delta Table
df_bronze.write.format("delta") \
    .mode(load_mode) \
    .option("mergeSchema", "true") \
    .saveAsTable(f"bronze_{source_name}")

print(f"Written to: bronze_{source_name}")
```

```python
# Cell 6: Validation
rows_written = spark.table(f"bronze_{source_name}").count()
print(f"Source rows: {df_raw.count()}")
print(f"Table total rows: {rows_written}")

assert rows_written > 0, f"FAIL: No rows in bronze_{source_name}"
print("PASS: Bronze load complete")
```

---

## Silver Layer Template

```python
# Cell 1: Parameters
source_table = "bronze_customers"
target_table = "silver_customers"
load_mode = "merge"  # merge | overwrite | append
merge_keys = ["customer_id"]
```

```python
# Cell 2: Imports
from pyspark.sql import functions as F
from pyspark.sql.types import *
from pyspark.sql.window import Window
from delta.tables import DeltaTable
```

```python
# Cell 3: Read Bronze Data
df_bronze = spark.read.table(source_table)
print(f"Bronze rows: {df_bronze.count()}")
```

```python
# Cell 4: Clean and Transform
df_clean = df_bronze \
    .withColumnRenamed("CustName", "customer_name") \
    .withColumn("customer_name", F.initcap(F.trim(F.col("customer_name")))) \
    .withColumn("email", F.lower(F.trim(F.col("email")))) \
    .withColumn("amount", F.col("amount").cast("decimal(18,2)")) \
    .filter(F.col("customer_id").isNotNull())
```

```python
# Cell 5: Deduplicate
window_spec = Window.partitionBy("customer_id").orderBy(F.col("_load_timestamp").desc())
df_dedup = df_clean \
    .withColumn("_row_num", F.row_number().over(window_spec)) \
    .filter(F.col("_row_num") == 1) \
    .drop("_row_num")
```

```python
# Cell 6: Write / Merge to Silver
if load_mode == "merge":
    delta_table = DeltaTable.forName(spark, target_table)
    delta_table.alias("target") \
        .merge(
            df_dedup.alias("source"),
            " AND ".join([f"target.{k} = source.{k}" for k in merge_keys])
        ) \
        .whenMatchedUpdateAll() \
        .whenNotMatchedInsertAll() \
        .execute()
else:
    df_dedup.write.format("delta") \
        .mode(load_mode) \
        .saveAsTable(target_table)
```

```python
# Cell 7: Validation
rows_written = spark.table(target_table).count()
print(f"Silver rows: {rows_written}")

# Null check on key columns
for col_name in merge_keys:
    null_count = spark.table(target_table).filter(F.col(col_name).isNull()).count()
    assert null_count == 0, f"FAIL: {col_name} has {null_count} nulls"
    print(f"PASS: {col_name} has 0 nulls")
```

---

## Gold Layer Template (Dimension)

```python
# Cell 1: Parameters
source_table = "silver_customers"
target_table = "dim_customer"
business_keys = ["customer_id"]
```

```python
# Cell 2: Imports
from pyspark.sql import functions as F
from pyspark.sql.types import *
from pyspark.sql.window import Window
from delta.tables import DeltaTable
```

```python
# Cell 3: Spark Config (Read-Optimized)
spark.conf.set("spark.sql.parquet.vorder.enabled", "true")
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")
```

```python
# Cell 4: Read Silver Data
df_silver = spark.read.table(source_table)
```

```python
# Cell 5: Build Dimension
df_dim = df_silver \
    .select("customer_id", "customer_name", "email", "city", "state") \
    .dropDuplicates(business_keys)

# Add surrogate key
df_dim = df_dim.withColumn(
    "customer_key",
    F.sha2(F.concat_ws("||", *[F.col(k) for k in business_keys]), 256)
)
```

```python
# Cell 6: Merge to Gold
DeltaTable.createIfNotExists(spark) \
    .tableName(target_table) \
    .addColumn("customer_key", StringType()) \
    .addColumn("customer_id", LongType()) \
    .addColumn("customer_name", StringType()) \
    .addColumn("email", StringType()) \
    .addColumn("city", StringType()) \
    .addColumn("state", StringType()) \
    .execute()

delta_table = DeltaTable.forName(spark, target_table)
delta_table.alias("target") \
    .merge(df_dim.alias("source"), "target.customer_key = source.customer_key") \
    .whenMatchedUpdateAll() \
    .whenNotMatchedInsertAll() \
    .execute()
```

```python
# Cell 7: Validation
row_count = spark.table(target_table).count()
print(f"Dimension rows: {row_count}")

# Check surrogate key uniqueness
dup_count = row_count - spark.table(target_table).dropDuplicates(["customer_key"]).count()
assert dup_count == 0, f"FAIL: {dup_count} duplicate surrogate keys"
print("PASS: All surrogate keys unique")
```

---

## Gold Layer Template (Fact)

```python
# Cell 1: Parameters
source_table = "silver_orders"
target_table = "fct_sales"
dim_tables = {"dim_customer": "customer_id", "dim_product": "product_id"}
```

```python
# Cell 2: Imports
from pyspark.sql import functions as F
from pyspark.sql.types import *
from delta.tables import DeltaTable
```

```python
# Cell 3: Spark Config (Read-Optimized)
spark.conf.set("spark.sql.parquet.vorder.enabled", "true")
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")
```

```python
# Cell 4: Read Source and Dimensions
df_source = spark.read.table(source_table)
df_dim_customer = spark.read.table("dim_customer")
df_dim_product = spark.read.table("dim_product")
```

```python
# Cell 5: Build Fact with Dimension Lookups
df_fact = df_source.alias("src") \
    .join(
        df_dim_customer.alias("dc"),
        F.col("src.customer_id") == F.col("dc.customer_id"),
        "left"
    ) \
    .join(
        df_dim_product.alias("dp"),
        F.col("src.product_id") == F.col("dp.product_id"),
        "left"
    ) \
    .select(
        F.col("dc.customer_key"),
        F.col("dp.product_key"),
        F.col("src.order_date"),
        F.col("src.quantity"),
        F.col("src.unit_price"),
        F.col("src.tax_amount")
    )
```

```python
# Cell 6: Write Fact Table
df_fact.write.format("delta") \
    .mode("overwrite") \
    .option("overwriteSchema", "true") \
    .saveAsTable(target_table)
```

```python
# Cell 7: Validation
row_count = spark.table(target_table).count()
print(f"Fact rows: {row_count}")

# Check for orphan dimension keys
for dim_table, key_col in dim_tables.items():
    dim_df = spark.read.table(dim_table)
    orphans = spark.table(target_table).alias("f") \
        .join(dim_df.alias("d"), f"f.{key_col.replace('_id', '_key')} = d.{key_col.replace('_id', '_key')}", "left_anti") \
        .count()
    print(f"Orphan {key_col.replace('_id', '_key')}s: {orphans}")
```

---

## Orchestration Notebook Template

```python
# Cell 1: Parameters
pipeline_name = "daily_load"
run_bronze = True
run_silver = True
run_gold = True
```

```python
# Cell 2: Define DAG
DAG = {
    "activities": [
        {
            "name": "Bronze_Customers",
            "path": "bronze/nb_bronze_customers",
            "timeoutPerCellInSeconds": 90,
            "args": {"load_mode": "append"}
        },
        {
            "name": "Bronze_Orders",
            "path": "bronze/nb_bronze_orders",
            "timeoutPerCellInSeconds": 120,
            "args": {"load_mode": "append"}
        },
        {
            "name": "Silver_Customers",
            "path": "silver/nb_silver_customers",
            "timeoutPerCellInSeconds": 120,
            "dependencies": ["Bronze_Customers"]
        },
        {
            "name": "Silver_Orders",
            "path": "silver/nb_silver_orders",
            "timeoutPerCellInSeconds": 120,
            "dependencies": ["Bronze_Orders"]
        },
        {
            "name": "Gold_Dim_Customer",
            "path": "gold/nb_gold_dim_customer",
            "timeoutPerCellInSeconds": 120,
            "dependencies": ["Silver_Customers"]
        },
        {
            "name": "Gold_Fact_Sales",
            "path": "gold/nb_gold_fct_sales",
            "timeoutPerCellInSeconds": 180,
            "dependencies": ["Silver_Customers", "Silver_Orders", "Gold_Dim_Customer"],
            "retry": 1,
            "retryIntervalInSeconds": 10
        }
    ],
    "timeoutInSeconds": 43200,
    "concurrency": 50
}
```

```python
# Cell 3: Execute Pipeline
notebookutils.notebook.runMultiple(DAG, {"displayDAGViaGraphviz": False})
print(f"Pipeline '{pipeline_name}' completed successfully")
```
