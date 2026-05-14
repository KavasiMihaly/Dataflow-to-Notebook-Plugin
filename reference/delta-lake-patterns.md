# Delta Lake Patterns for Fabric

Reference patterns for Delta Lake operations in Microsoft Fabric lakehouses. Used by all Fabric agents for consistent data management.

---

## MERGE / Upsert Pattern

### PySpark API (preferred)

```python
from delta.tables import DeltaTable
from pyspark.sql import functions as F

delta_table = DeltaTable.forName(spark, "silver_customers")

delta_table.alias("target") \
    .merge(
        source_df.alias("source"),
        "target.customer_id = source.customer_id"
    ) \
    .whenMatchedUpdate(
        condition="source.modified_date > target.modified_date",
        set={
            "customer_name": "source.customer_name",
            "email": "source.email",
            "modified_date": "source.modified_date"
        }
    ) \
    .whenNotMatchedInsertAll() \
    .execute()
```

### Spark SQL

```sql
%%sql
MERGE INTO silver.customers AS target
USING bronze.customers_staging AS source
ON target.customer_id = source.customer_id
WHEN MATCHED AND source.modified_date > target.modified_date THEN
    UPDATE SET
        target.customer_name = source.customer_name,
        target.email = source.email,
        target.modified_date = source.modified_date
WHEN NOT MATCHED THEN
    INSERT *
```

---

## Append with Schema Evolution

Use for bronze layer ingestion where source schemas may evolve over time.

```python
df.write.format("delta") \
    .mode("append") \
    .option("mergeSchema", "true") \
    .saveAsTable("bronze_orders")
```

**Session-level auto-merge (alternative):**
```python
spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")
```

**Schema overwrite (use for full refresh):**
```python
df.write.format("delta") \
    .mode("overwrite") \
    .option("overwriteSchema", "true") \
    .saveAsTable("silver_orders")
```

---

## Schema Enforcement vs Evolution by Layer

| Layer | Schema Strategy | Option | Rationale |
|-------|----------------|--------|-----------|
| Bronze | Evolution | `mergeSchema: true` | Accept new columns from source |
| Silver | Enforcement | Default (no option) | Schema validated during transform |
| Gold | Enforcement | Default (no option) | Schema defined by business model |

---

## OPTIMIZE and VACUUM

### OPTIMIZE (bin-compaction)

```sql
%%sql
-- Basic optimize
OPTIMIZE silver.sales_orders;

-- With predicate (only optimize recent partitions)
OPTIMIZE silver.sales_orders WHERE order_date >= '2025-01-01';

-- Z-ORDER (co-locate data for common query patterns)
OPTIMIZE silver.sales_orders ZORDER BY (customer_id, order_date);

-- V-ORDER (Fabric-specific, improves read performance)
OPTIMIZE gold.fact_sales VORDER;

-- Combined Z-ORDER + V-ORDER
OPTIMIZE gold.fact_sales WHERE year = 2025
ZORDER BY (customer_id) VORDER;
```

### VACUUM (remove old files)

```sql
%%sql
-- Remove files older than default retention (7 days)
VACUUM silver.sales_orders;

-- Custom retention
VACUUM silver.sales_orders RETAIN 168 HOURS;
```

**Warning:** VACUUM removes files needed for time travel beyond the retention period.

---

## V-ORDER Configuration

V-ORDER is a Fabric-specific write-time optimization that improves read performance by ~50% with ~15% write overhead.

### By Layer Recommendation

| Layer | V-ORDER | Reason |
|-------|---------|--------|
| Bronze | OFF | Prioritize write speed for ingestion |
| Silver | OFF | Prioritize transform speed |
| Gold | ON | Optimize for read-heavy analytics queries |

### Enable V-ORDER

```python
# Session-level
spark.conf.set("spark.sql.parquet.vorder.enabled", "true")

# Write-level
df.write.format("delta") \
    .mode("overwrite") \
    .option("parquet.vorder.enabled", "true") \
    .saveAsTable("gold.fact_sales")
```

```sql
%%sql
-- Table property
ALTER TABLE gold.fact_sales
SET TBLPROPERTIES("delta.parquet.vorder.enabled" = "true");
```

---

## Partition Strategies

### When to Partition

| Use Case | Strategy | Example |
|----------|----------|---------|
| Large fact tables (>1B rows) | Partition by date | `partitionBy("year", "month")` |
| Medium tables (10M-1B rows) | No partition, use Z-ORDER | `ZORDER BY (key_column)` |
| Small tables (<10M rows) | No partition needed | Default layout |

### Partition Example

```python
df.write.format("delta") \
    .mode("overwrite") \
    .partitionBy("year", "quarter") \
    .saveAsTable("fct_sales")
```

### Fabric Best Practices
- Prefer fewer, larger partitions over many small ones
- V-ORDER is generally preferred over Z-ORDER in Fabric
- Do not partition dimension tables (they are small)
- Only partition fact tables when they exceed 1 billion rows

---

## Time Travel

### Read Historical Versions

```python
# By version number
df_v0 = spark.read.format("delta") \
    .option("versionAsOf", 0) \
    .load("Tables/silver_customers")

# By timestamp
df_historical = spark.read.format("delta") \
    .option("timestampAsOf", "2025-01-15T10:00:00") \
    .load("Tables/silver_customers")
```

### View History

```python
from delta.tables import DeltaTable

delta_table = DeltaTable.forPath(spark, "Tables/silver_customers")
history_df = delta_table.history()
display(history_df)
```

```sql
%%sql
DESCRIBE HISTORY silver.customers;
```

### Restore

```python
delta_table = DeltaTable.forPath(spark, "Tables/silver_customers")
delta_table.restoreToVersion(1)
# or
delta_table.restoreToTimestamp("2025-01-15")
```

---

## Table Properties

### Create with Properties

```sql
%%sql
CREATE TABLE gold.fact_sales (
    customer_key STRING,
    order_date DATE,
    amount DECIMAL(18,2)
) USING DELTA
TBLPROPERTIES(
    "delta.parquet.vorder.enabled" = "true",
    "delta.enableChangeDataFeed" = "true"
);
```

### Create with DeltaTable API

```python
from delta.tables import DeltaTable
from pyspark.sql.types import *

DeltaTable.createIfNotExists(spark) \
    .tableName("gold.fact_sales") \
    .addColumn("customer_key", StringType()) \
    .addColumn("order_date", DateType()) \
    .addColumn("amount", DecimalType(18, 2)) \
    .execute()
```

---

## Change Data Feed

Enable to track row-level changes for downstream consumers.

```sql
%%sql
-- Enable
ALTER TABLE silver.customers SET TBLPROPERTIES (delta.enableChangeDataFeed = true);

-- Query changes from version
SELECT * FROM table_changes('silver.customers', 2);

-- Query changes from timestamp
SELECT * FROM table_changes('silver.customers', '2025-01-15');
```

---

## Spark Configuration by Layer

| Layer | Setting | Value | Reason |
|-------|---------|-------|--------|
| Bronze | `spark.sql.parquet.vorder.enabled` | `false` | Fast ingestion |
| Bronze | `spark.databricks.delta.optimizeWrite.enabled` | `false` | Skip file optimization |
| Bronze | `spark.databricks.delta.collect.stats` | `false` | Skip stats collection |
| Silver | `spark.sql.parquet.vorder.enabled` | `false` | Transform speed |
| Silver | `spark.databricks.delta.optimizeWrite.binSize` | `157m` | Balanced file sizes |
| Gold | `spark.sql.parquet.vorder.enabled` | `true` | Optimized reads |
| Gold | `spark.databricks.delta.optimizeWrite.enabled` | `true` | Optimized file layout |
| Gold | `spark.databricks.delta.optimizeWrite.binSize` | `1gb` | Large read-optimized files |

### Apply Configuration in Notebook

```python
# Bronze layer config
spark.conf.set("spark.sql.parquet.vorder.enabled", "false")
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "false")

# Gold layer config
spark.conf.set("spark.sql.parquet.vorder.enabled", "true")
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")
spark.conf.set("spark.databricks.delta.optimizeWrite.binSize", "1gb")
```
