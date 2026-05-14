# Testing Patterns for Fabric PySpark Notebooks

Data quality validation approaches for each layer of the medallion architecture. Agents use these patterns to generate validation cells in notebooks.

---

## Testing Philosophy

Unlike dbt (which has a built-in test framework), Fabric notebooks embed validation directly as code cells. Tests run as the final cells of each notebook, using Python assertions that fail the notebook on violation.

**Convention:** Every notebook's final cell is a validation cell that:
1. Checks row counts
2. Validates key columns for nulls
3. Checks uniqueness where required
4. Prints PASS/FAIL status

---

## Level 1: Row Count Validation

The simplest and most universal check. Every notebook must include this.

```python
# --- Validation: Row Count ---
source_count = df_raw.count()
target_count = spark.table(f"bronze_{source_name}").count()

print(f"Source rows: {source_count}")
print(f"Target rows: {target_count}")

assert target_count > 0, f"FAIL: Target table bronze_{source_name} is empty"
print("PASS: Row count validation")
```

### Row Count Drift Detection (for recurring loads)
```python
# Check that row count is within expected range
expected_count = 10000  # From previous runs or config
tolerance = 0.20  # 20% drift tolerance

min_rows = int(expected_count * (1 - tolerance))
max_rows = int(expected_count * (1 + tolerance))

actual_count = spark.table(target_table).count()
assert min_rows <= actual_count <= max_rows, \
    f"FAIL: Row count {actual_count} outside expected range [{min_rows}, {max_rows}]"
print(f"PASS: Row count {actual_count} within tolerance")
```

---

## Level 2: Null Checks on Key Columns

Validate that critical columns contain no nulls.

```python
# --- Validation: Null Checks ---
from pyspark.sql import functions as F

critical_columns = ["customer_id", "order_date", "amount"]

for col_name in critical_columns:
    null_count = spark.table(target_table) \
        .filter(F.col(col_name).isNull()) \
        .count()
    assert null_count == 0, f"FAIL: {col_name} has {null_count} nulls"
    print(f"PASS: {col_name} has 0 nulls")
```

### Null Percentage Check (for non-critical columns)
```python
total_rows = spark.table(target_table).count()
nullable_columns = ["email", "phone", "address"]
max_null_pct = 0.10  # Allow up to 10% nulls

for col_name in nullable_columns:
    null_count = spark.table(target_table) \
        .filter(F.col(col_name).isNull()) \
        .count()
    null_pct = null_count / total_rows if total_rows > 0 else 0
    assert null_pct <= max_null_pct, \
        f"FAIL: {col_name} has {null_pct:.1%} nulls (max {max_null_pct:.0%})"
    print(f"PASS: {col_name} null rate {null_pct:.1%}")
```

---

## Level 3: Uniqueness Validation

Verify primary keys and surrogate keys are unique.

```python
# --- Validation: Uniqueness ---
df_target = spark.table(target_table)
total_rows = df_target.count()

# Single column uniqueness
pk_column = "customer_id"
distinct_count = df_target.select(pk_column).distinct().count()
dup_count = total_rows - distinct_count

assert dup_count == 0, f"FAIL: {dup_count} duplicate {pk_column}s found"
print(f"PASS: {pk_column} is unique ({total_rows} rows)")
```

### Composite Key Uniqueness
```python
composite_keys = ["order_id", "line_number"]
distinct_count = df_target.select(composite_keys).distinct().count()
dup_count = total_rows - distinct_count

assert dup_count == 0, \
    f"FAIL: {dup_count} duplicate composite keys ({', '.join(composite_keys)})"
print(f"PASS: Composite key unique ({total_rows} rows)")
```

---

## Level 4: Referential Integrity

Check that foreign keys in fact tables exist in dimension tables.

```python
# --- Validation: Referential Integrity ---
fact_df = spark.table("fct_sales")
dim_customer = spark.table("dim_customer")

# Find orphan records (fact FK not in dimension PK)
orphan_records = fact_df.alias("f") \
    .join(
        dim_customer.alias("d"),
        F.col("f.customer_key") == F.col("d.customer_key"),
        "left_anti"
    )

orphan_count = orphan_records.count()
assert orphan_count == 0, \
    f"FAIL: {orphan_count} orphan customer_keys in fct_sales"
print(f"PASS: Referential integrity OK for customer_key")
```

### Multi-Dimension Integrity Check
```python
dimension_checks = {
    "dim_customer": "customer_key",
    "dim_product": "product_key",
    "dim_date": "date_key"
}

fact_df = spark.table("fct_sales")
all_passed = True

for dim_table, key_col in dimension_checks.items():
    dim_df = spark.table(dim_table)
    orphans = fact_df.alias("f") \
        .join(dim_df.alias("d"), f"f.{key_col} = d.{key_col}", "left_anti") \
        .count()

    if orphans > 0:
        print(f"FAIL: {orphans} orphan {key_col}s (missing in {dim_table})")
        all_passed = False
    else:
        print(f"PASS: {key_col} integrity OK")

assert all_passed, "Referential integrity check failed"
```

---

## Level 5: Data Type Validation

Verify columns have expected types after transformation.

```python
# --- Validation: Data Types ---
from pyspark.sql.types import *

expected_types = {
    "customer_id": LongType(),
    "customer_name": StringType(),
    "order_date": DateType(),
    "amount": DecimalType(18, 2),
    "is_active": BooleanType()
}

actual_schema = {f.name: f.dataType for f in spark.table(target_table).schema.fields}

for col_name, expected_type in expected_types.items():
    actual_type = actual_schema.get(col_name)
    assert actual_type == expected_type, \
        f"FAIL: {col_name} is {actual_type}, expected {expected_type}"
    print(f"PASS: {col_name} type is {expected_type}")
```

---

## Level 6: Business Rule Assertions

Custom validations specific to the business domain.

```python
# --- Validation: Business Rules ---

# Amount should be non-negative
negative_amounts = spark.table(target_table) \
    .filter(F.col("amount") < 0) \
    .count()
assert negative_amounts == 0, \
    f"FAIL: {negative_amounts} records with negative amounts"
print("PASS: All amounts non-negative")

# Date within valid range
invalid_dates = spark.table(target_table) \
    .filter(
        (F.col("order_date") < F.lit("2020-01-01")) |
        (F.col("order_date") > F.lit("2030-12-31"))
    ) \
    .count()
assert invalid_dates == 0, \
    f"FAIL: {invalid_dates} records with out-of-range dates"
print("PASS: All dates in valid range")

# Status must be in allowed values
valid_statuses = ["ACTIVE", "INACTIVE", "PENDING"]
invalid_status = spark.table(target_table) \
    .filter(~F.col("status").isin(valid_statuses)) \
    .count()
assert invalid_status == 0, \
    f"FAIL: {invalid_status} records with invalid status"
print("PASS: All statuses valid")
```

---

## Level 7: Cross-Table Consistency

Verify aggregates match between layers.

```python
# --- Validation: Cross-Table Consistency ---

# Total amount in fact should match silver source
silver_total = spark.table("silver_orders") \
    .agg(F.sum("amount").alias("total")) \
    .first()["total"]

gold_total = spark.table("fct_sales") \
    .agg(F.sum("amount").alias("total")) \
    .first()["total"]

# Allow small rounding tolerance
tolerance = 0.01
diff = abs(float(silver_total) - float(gold_total))
assert diff < tolerance, \
    f"FAIL: Amount mismatch - Silver: {silver_total}, Gold: {gold_total}"
print(f"PASS: Totals match (diff: {diff})")
```

---

## Quality Checks by Layer Summary

| Layer | Required Checks | Optional Checks |
|-------|----------------|-----------------|
| Bronze | Row count > 0, Schema compliance | Row count drift |
| Silver | Null checks on keys, Uniqueness, Data types | Deduplication verification, Business rules |
| Gold (Dim) | Surrogate key uniqueness, Null checks | SCD correctness |
| Gold (Fact) | Referential integrity, Row count | Cross-table consistency, Business rules |

---

## PySpark Built-in Testing Utilities

For unit-testing transforms outside of notebooks:

```python
from pyspark.testing.utils import assertDataFrameEqual, assertSchemaEqual

# Assert two DataFrames are equal (content and schema)
assertDataFrameEqual(actual_df, expected_df)

# Assert only schemas match
assertSchemaEqual(actual_df.schema, expected_df.schema)
```

---

## Great Expectations Integration (Advanced)

For production-grade data quality, Great Expectations can be installed in Fabric Environments.

**Setup:** Add `great_expectations` as a public library in Fabric Environment settings.

```python
import great_expectations as gx

context = gx.get_context()
suite = context.suites.add(gx.ExpectationSuite(name="bronze_suite"))

# Add expectations
suite.add_expectation(
    gx.expectations.ExpectTableRowCountToBeBetween(min_value=1000, max_value=50000)
)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToNotBeNull(column="customer_id")
)
suite.add_expectation(
    gx.expectations.ExpectCompoundColumnsToBeUnique(column_list=["order_id", "line_number"])
)

# Validate
data_source = context.data_sources.add_spark(name="source")
data_asset = data_source.add_dataframe_asset(name="data")
batch_def = data_asset.add_batch_definition_whole_dataframe("batch")

validation = gx.ValidationDefinition(data=batch_def, suite=suite, name="validation")
results = validation.run(batch_parameters={"dataframe": df})
print(results)
```

**Note:** Great Expectations is optional. The assertion-based patterns above are sufficient for most use cases and have zero dependencies.
