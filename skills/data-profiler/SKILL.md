---
name: data-profiler
description: Automatically profile SQL Server tables and CSV files with intelligent analysis. Detects primary key candidates, infers data types from CSV data, calculates column statistics (nulls, cardinality, data types), identifies data quality issues, and recommends appropriate dbt tests. Use when exploring source data, creating staging models, or validating data quality before transformation. Generates comprehensive profiling reports with test recommendations.
allowed-tools: Bash Read Glob Write
---

# Data Profiler

Automatically profile SQL Server tables and CSV files to understand data characteristics and guide dbt model development.

## Overview

This skill provides automated data profiling with intelligent analysis to:
- Profile SQL Server tables or CSV files automatically (no manual queries needed)
- Infer data types from CSV data (pandas dtype detection + validation)
- Detect primary key candidates based on cardinality and nullness
- Calculate comprehensive statistics (nulls, distinct values, min/max, patterns)
- Identify data quality issues (duplicates, nulls, outliers)
- Recommend appropriate dbt tests based on data patterns
- Generate actionable insights for staging model creation
- Export detailed profiling reports to `1 - Documentation/data-profiles/` for persistent reference

## Connection Details

**SQL Server:**
- **Server**: localhost
- **Database**: Set via SQL_DATABASE env var
- **Authentication**: SQL Server Authentication
- **User**: Set via `SQL_USER` env var (empty = Windows Auth)
- **Mode**: Read-only (SELECT statements only)

**CSV Files:**
- **Location**: Any accessible path (typically `2 - Source Files/`)
- **Format**: Standard CSV with header row
- **Type Inference**: Automatic pandas dtype detection
- **Supported Types**: int, float, datetime, string, boolean

## Usage

The skill is invoked through the Python script located in the skill's folder.

**Script Location**: `${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py`

**Important**: Always use the full path to the script, not a relative path. The script is in the skill folder, not the project folder.

### Profile SQL Server Tables

#### Profile a single table

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table customers
```

**Output**:
- Comprehensive profile of all columns
- Primary key candidate detection
- Data quality insights
- Test recommendations
- Saves to `1 - Documentation/data-profiles/profile_customers_TIMESTAMP.json`

#### Profile a schema-qualified table

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table raw.epraccur
```

**Output**: Correctly splits `raw.epraccur` into schema `raw` and table `epraccur` for metadata queries. The full schema-qualified name is used for data queries.

#### Profile multiple tables

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --tables raw.customers raw.orders dbo.products
```

**Output**: Profiles each table and generates individual reports

### Profile CSV Files

#### Profile a single CSV file

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file "2 - Source Files/dft-road-casualty-statistics-casualty-2024.csv"
```

**Output**:
- Automatic type inference from data
- Column statistics and patterns
- Primary key candidate detection
- Test recommendations
- Saves to `1 - Documentation/data-profiles/profile_dft-road-casualty-statistics-casualty-2024_TIMESTAMP.json`

#### Profile multiple CSV files with glob pattern

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --files "2 - Source Files/dft-road-casualty-statistics-casualty-*.csv"
```

**Output**: Profiles all matching CSV files

#### Profile specific columns only

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file data.csv --columns customer_id order_date amount
```

**Output**: Profiles only specified columns

### Profile with sample size limit

```bash
# SQL Server table
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table large_table --sample 10000

# CSV file
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file large_file.csv --sample 10000
```

**Output**: Profiles based on sample of 10,000 rows for faster analysis

### Quick profile (basic stats only)

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file orders.csv --quick
```

**Output**: Fast profile with row count, column count, and basic statistics only

### JSON output for automation

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file customers.csv --format json
```

**Output**: Structured JSON for integration with other tools

**Note**: JSON format is recommended for Claude Code agent workflows to avoid Unicode encoding issues on Windows consoles

### Verbose logging

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file customers.csv --verbose
```

**Output**: Detailed logging of profiling process

### Custom output directory

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file customers.csv --output-dir "path/to/custom/location"
```

**Default Behavior**:
- Profiles are saved to `1 - Documentation/data-profiles/` by default
- This ensures profiles are persisted, version controlled, and accessible to all agents
- JSON format is used by default for structured data

**Custom Location**:
- Use `--output-dir` to specify alternative location
- Useful for temporary analysis or agent-specific workflows
- Example: `--output-dir "6 - Data Exports"` for transient data

## CSV Type Inference

The profiler automatically infers data types from CSV data:

### Type Detection Process
1. **Numeric Detection**: Attempts `pd.to_numeric()` conversion
   - Success threshold: 90% of values convert successfully
   - Maps to: `bigint` (int64) or `decimal` (float64)

2. **Datetime Detection**: Attempts `pd.to_datetime()` conversion
   - Success threshold: 90% of values convert successfully
   - Maps to: `datetime2` (datetime64[ns])

3. **Boolean Detection**: Identifies True/False or 0/1 patterns
   - Maps to: `bit` (bool)

4. **String Fallback**: Any column not matching above
   - Maps to: `nvarchar` (object)

### Type Mapping (CSV → SQL Server)

| Pandas dtype | SQL Server type | Notes |
|--------------|----------------|-------|
| int64 | bigint | Whole numbers |
| float64 | decimal | Decimals, scientific notation |
| datetime64[ns] | datetime2 | Dates and timestamps |
| bool | bit | Boolean values |
| object | nvarchar | Text, mixed types |

### Handling Ambiguous Data

- **Mixed types**: Classified as `nvarchar`
- **Numeric strings**: If >90% convert, treated as numeric
- **Date strings**: Must match standard formats (ISO 8601, etc.)
- **Large integers**: May be read as float due to pandas behavior

## Sample Output

```
=== Data Profile: dft-road-casualty-statistics-casualty-2024 ===

Table Statistics:
  - Total Rows: 125,432
  - Total Columns: 15
  - Primary Key: casualty_reference (detected)
  - Profile Date: 2026-01-11 14:30:22
  - Source: CSV file (types inferred)

Column Profiles:

┌─────────────────────────────────────────────────────────────────────┐
│ casualty_reference                                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Data Type      : bigint (inferred from int64)                       │
│ Nulls          : 0 (0.0%)                                           │
│ Distinct Values: 125,432 (100.0%)                                   │
│ Min Value      : 202401000001                                       │
│ Max Value      : 202401125432                                       │
│ ✓ PRIMARY KEY CANDIDATE                                             │
│                                                                     │
│ Recommended Tests:                                                  │
│   - unique                                                          │
│   - not_null                                                        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ accident_reference                                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Data Type      : nvarchar (inferred from object)                    │
│ Nulls          : 0 (0.0%)                                           │
│ Distinct Values: 98,745 (78.7%)                                     │
│ Min Length     : 8                                                  │
│ Max Length     : 127                                                │
│ Pattern        : Valid email format (99.5%)                         │
│ ⚠️  Contains nulls                                                   │
│                                                                     │
│ Recommended Tests:                                                  │
│   - not_null (if required by business logic)                        │
│   - email format validation (custom test)                           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ casualty_severity                                                   │
├─────────────────────────────────────────────────────────────────────┤
│ Data Type      : bigint (inferred from int64)                       │
│ Nulls          : 0 (0.0%)                                           │
│ Distinct Values: 3 (0.002%)                                         │
│ Values         : 1 (78,234), 2 (35,198), 3 (12,000)                 │
│                                                                     │
│ Recommended Tests:                                                  │
│   - not_null                                                        │
│   - accepted_values: [1, 2, 3]                                      │
└─────────────────────────────────────────────────────────────────────┘

... (all columns profiled)

Data Quality Issues:
  ⚠️  age_of_casualty has 1,234 nulls (0.98%) - Handle in staging model
  ⚠️  casualty_home_area_type has 5,432 nulls (4.3%) - Consider if needed
  ⚠️  casualty_severity has only 3 distinct values - Use accepted_values test

Recommendations for Staging Model:
  1. Use casualty_reference as primary key
  2. Add unique + not_null tests to casualty_reference
  3. Add not_null tests to: accident_reference, casualty_class, casualty_severity
  4. Add accepted_values test to casualty_severity column
  5. Handle nulls in age_of_casualty and casualty_home_area_type
  6. Add relationship test from accident_reference to accidents table

Suggested dbt YAML:
```yaml
models:
  - name: stg_dft__casualties
    description: "Staging model for road casualty statistics"
    columns:
      - name: casualty_reference
        description: "Primary key for casualties"
        data_tests:
          - unique
          - not_null

      - name: email
        description: "Customer email address"
        data_tests:
          - not_null

      - name: status
        description: "Customer account status"
        data_tests:
          - not_null
          - accepted_values:
              values: ['Active', 'Inactive', 'Pending']
```

Export saved to: 1 - Documentation/data-profiles/profile_customers_20260111_143022.json
```

## What This Skill Analyzes

### For All Columns:
- Data type and precision
- Null count and percentage
- Distinct value count and cardinality
- Min/max values (for numeric/date columns)
- Min/max length (for string columns)
- Most common values (top 5)

### For Potential Primary Keys:
- Uniqueness (100% distinct = strong PK candidate)
- Nullness (0% null = strong PK candidate)
- Cardinality (high = good PK, low = dimension attribute)
- Data type (integer/bigint = typical PK)

### For String Columns:
- Length distribution
- Pattern detection (email, phone, URL, etc.)
- Character set analysis

### For Numeric Columns:
- Range (min, max, avg)
- Distribution (percentiles)
- Outlier detection

### For Date Columns:
- Date range (earliest, latest)
- Gaps in dates
- Recency analysis

## Test Recommendations Logic

The profiler automatically recommends tests based on data patterns:

### Primary Key Tests
- **Triggers**: 100% distinct values + 0% nulls
- **Recommends**: `unique` + `not_null`

### Not Null Tests
- **Triggers**: 0% nulls + important column (PK, FK, measure)
- **Recommends**: `not_null`

### Accepted Values Tests
- **Triggers**: Low cardinality (< 10 distinct values)
- **Recommends**: `accepted_values` with list of values

### Relationships Tests
- **Triggers**: Column name ends with `_id` or `_key` + not the PK
- **Recommends**: `relationships` to related dimension

### Custom Tests
- **Email format**: Pattern matches email structure
- **Date range**: Dates in future or far past
- **Negative values**: Where business logic prohibits them
- **String length**: Exceeds expected max

## Integration with Agents

### dbt-staging-builder Agent
The primary use case - dbt-staging-builder uses data-profiler to:
1. **CSV Files**: Profile source CSV to understand structure before loading
2. **SQL Tables**: Profile raw tables after loading to SQL Server
3. Identify primary key for surrogate key generation
4. Detect nullable columns for null handling
5. Get test recommendations for schema.yml
6. Understand inferred data types for SQL casting

**Workflow (CSV source)**:
```bash
# dbt-staging-builder invokes data-profiler on CSV
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file "2 - Source Files/casualties-2024.csv"

# Reviews inferred types and profile
# Creates staging model with appropriate:
#   - Type casting (CSV string → SQL types)
#   - Primary key selection
#   - Null handling
#   - Initial tests
```

**Workflow (SQL table)**:
```bash
# dbt-staging-builder invokes data-profiler on raw table
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table raw_customers

# Reviews profile output
# Creates staging model with appropriate:
#   - Primary key selection
#   - Null handling
#   - Type casting
#   - Initial tests
```

### business-analyst Agent
Use during discovery phase to:
- Understand data landscape from CSV files or SQL tables
- Identify data quality issues
- Document data characteristics
- Inform requirements

### dbt-test-writer Agent
Use to design comprehensive tests:
- Understand which columns need tests
- Get baseline for test expectations
- Identify edge cases
- Design custom tests for patterns

### Accessing Persisted Profiles

All agents can reference previously generated profiles from the documentation folder:

**Profile Location**: `1 - Documentation/data-profiles/`

**Reading Profiles**:
```python
# Agents can read JSON profiles using Read tool
profile_path = "1 - Documentation/data-profiles/profile_customers_20260113_143022.json"

# Profile contains:
# - table_name, total_rows, total_columns
# - primary_key_candidates
# - columns[] with data_type, null_percentage, distinct_count, etc.
# - quality_issues[]
# - recommendations[]
```

**Benefits**:
- **dbt-staging-builder**: Reference existing profiles when creating related models
- **business-analyst**: Include profiles in requirement documentation
- **dbt-test-writer**: Access data patterns without re-profiling
- **dbt-dimension-builder**: Understand SCD candidates from cardinality patterns
- **Version Control**: Track data structure changes over time

**Best Practice**: Profile once, reference many times. Profiles are timestamped and permanent.

## Advanced Usage

### Profile with custom confidence threshold

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table customers --pk-threshold 0.95
```

**Default threshold**: 99% distinct + 1% nulls
**Custom threshold**: 95% distinct + 5% nulls (more lenient)

### Profile only specific columns

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table customers --columns customer_id email status
```

**Output**: Profiles only specified columns for faster analysis

### Compare before/after transformation

```bash
# Profile source table
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table raw_customers --output raw_profile.csv

# Profile staging model after transformation
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table stg_erp__customers --output stg_profile.csv

# Compare the two CSV files
```

### Generate dbt YAML scaffold

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table customers --generate-yaml
```

**Output**: Generates ready-to-use dbt schema.yml with:
- Column names and descriptions
- Recommended tests
- Primary key marked

## Output Formats

### JSON (Default for Persistence)
Structured JSON saved to `1 - Documentation/data-profiles/` for automation and agent integration.

**Benefits**:
- Structured data for programmatic access
- Avoids Unicode encoding issues on Windows
- Easy to parse by agents using Read tool
- Version control friendly

### Human-Readable
Formatted text with boxes and symbols for easy reading in terminal.

**Use Case**: Quick visual inspection during development

### CSV
Structured export with columns:
- column_name
- data_type
- null_count
- null_percentage
- distinct_count
- cardinality_percentage
- min_value
- max_value
- is_pk_candidate
- recommended_tests

### JSON
Structured JSON for automation and integration:
```json
{
  "table_name": "customers",
  "total_rows": 125432,
  "total_columns": 15,
  "primary_key_candidate": "customer_id",
  "profile_date": "2026-01-11T14:30:22",
  "columns": [
    {
      "name": "customer_id",
      "type": "bigint",
      "nulls": 0,
      "null_pct": 0.0,
      "distinct": 125432,
      "cardinality_pct": 100.0,
      "min": 1,
      "max": 125432,
      "is_pk_candidate": true,
      "recommended_tests": ["unique", "not_null"]
    }
  ],
  "quality_issues": [
    "phone_number has 12,345 nulls (9.8%)"
  ],
  "recommendations": [
    "Use customer_id as primary key",
    "Add unique + not_null tests to customer_id"
  ]
}
```

### dbt YAML
Generate ready-to-use schema.yml:
```yaml
models:
  - name: stg_source__customers
    columns:
      - name: customer_id
        data_tests:
          - unique
          - not_null
      - name: email
        data_tests:
          - not_null
```

## Common Patterns

### Quick table inspection before modeling

```bash
# Profile the table
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table raw_customers

# Review output and identify:
# - Primary key: customer_id
# - Nullable columns: phone_number (9.8%)
# - Categorical columns: status (3 values)

# Create staging model based on insights
```

### Batch profile all source tables

```bash
# Get list of tables
python "${CLAUDE_PLUGIN_ROOT}/skills/sql-server-reader/scripts/query_sql_server.py" --list-tables

# Profile each source table
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --tables customers orders products line_items
```

### Data quality validation

```bash
# Profile to establish baseline
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table orders --output baseline.csv

# After data cleanup
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table orders --output after_cleanup.csv

# Compare null percentages and data quality metrics
```

## Performance Considerations

### For Large Tables (> 1M rows):
- Use `--sample` to limit profiling to representative sample
- Profile specific columns with `--columns` instead of all columns
- Use `--quick` mode for basic statistics only

### Recommended Sample Sizes:
- Small tables (< 100K): Full table scan (no sample)
- Medium tables (100K - 1M): Sample 100K rows
- Large tables (> 1M): Sample 100K - 500K rows
- Very large tables (> 10M): Sample 500K - 1M rows

### Query Optimization:
The profiler uses efficient SQL:
- Single pass for basic statistics
- Minimizes distinct value calculations
- Avoids full table scans where possible
- Leverages indexes when available

## Safety Features

### Read-Only Mode
- Only SELECT statements permitted
- Uses sql-server-reader connection (read-only)
- No modifications to database

### Query Validation
- Validates all queries before execution
- Blocks write operations
- Timeout protection for long-running queries

### Resource Management
- Configurable sample size limits
- Query timeout settings
- Memory-efficient pandas operations

## Requirements

### Python Dependencies
- `pyodbc` - SQL Server ODBC driver
- `pandas` - Data manipulation
- `numpy` - Statistical calculations
- `sqlalchemy` - Database connections
- Standard library: `argparse`, `json`, `pathlib`, `datetime`

### Installation
```bash
pip install pyodbc pandas numpy sqlalchemy
```

### SQL Server Requirements
- Read access to target database
- ODBC Driver 17+ for SQL Server
- Same connection requirements as sql-server-reader

## Comparison with Other Tools

### vs. sql-server-reader
| Feature | sql-server-reader | data-profiler |
|---------|-------------------|---------------|
| Query execution | ✅ Manual queries | ✅ Automated profiling |
| List tables | ✅ Yes | ❌ Use sql-server-reader |
| Table schemas | ✅ Yes | ❌ Use sql-server-reader |
| Column statistics | ❌ Manual | ✅ Automatic |
| PK detection | ❌ No | ✅ Yes |
| Test recommendations | ❌ No | ✅ Yes |
| Data quality insights | ❌ No | ✅ Yes |
| Pattern detection | ❌ No | ✅ Yes |

**Recommendation**: Use both tools together
- sql-server-reader: Ad-hoc queries, table exploration, exports
- data-profiler: Comprehensive table analysis, model planning

### vs. business-analyst Agent
- **business-analyst**: Strategic discovery, requirements gathering
- **data-profiler**: Tactical profiling, automated analysis

business-analyst can USE data-profiler to accelerate discovery.

### vs. Manual Profiling
Manual approach requires 10+ queries per table:
```sql
-- Row count
SELECT COUNT(*) FROM table

-- Null counts per column
SELECT COUNT(*) FROM table WHERE col1 IS NULL
SELECT COUNT(*) FROM table WHERE col2 IS NULL
-- ... repeat for every column

-- Distinct values
SELECT COUNT(DISTINCT col1) FROM table
-- ... repeat for every column
```

data-profiler automates all of this in a single command.

## Troubleshooting

### Connection Issues
Use sql-server-reader test connection:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sql-server-reader/scripts/query_sql_server.py" --test-connection
```

### Table Not Found
Verify table exists:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sql-server-reader/scripts/query_sql_server.py" --list-tables
```

### Slow Profiling
Use sample for large tables:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table large_table --sample 50000
```

### Memory Issues
Profile columns individually:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table huge_table --columns id name status
```

### Unicode Encoding Issues (Windows)
**Problem**: On Windows, the console may fail to display Unicode characters (emoji, box-drawing) with error:
```
UnicodeEncodeError: 'charmap' codec can't encode characters
```

**Solutions**:

1. **Use JSON format** (Recommended for automation):
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file data.csv --format json
```

2. **Set UTF-8 encoding environment variable**:
```bash
# PowerShell
$env:PYTHONIOENCODING="utf-8"
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file data.csv

# Command Prompt
set PYTHONIOENCODING=utf-8
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file data.csv
```

3. **Redirect output to file**:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --file data.csv > profile_output.txt
```

**Note**: JSON format is recommended for Claude Code agent workflows to avoid encoding issues entirely.

## Best Practices

### When to Profile
1. **Before creating staging models**: Understand source data structure
2. **During discovery**: Initial data exploration
3. **Before adding tests**: Understand data patterns for test design
4. **After data quality issues**: Validate improvements
5. **Documentation**: Generate data dictionaries

### Profiling Workflow
1. List all tables with sql-server-reader
2. Profile each source table with data-profiler
3. Review primary key candidates and data quality issues
4. Create staging models based on insights
5. Implement recommended tests
6. Validate with dbt-test-coverage-analyzer

### Documentation
Profiles are automatically saved to `1 - Documentation/data-profiles/` with benefits:
- **Persistent**: Profiles are version controlled and permanent
- **Accessible**: All agents can reference profiles without re-profiling
- **Traceable**: Timestamped filenames track data evolution
- **Shareable**: Include in data dictionaries and model documentation
- **Comparable**: Track data quality metrics over time

**Organization**:
```
1 - Documentation/
└── data-profiles/
    ├── profile_customers_20260113_143022.json
    ├── profile_orders_20260113_143045.json
    ├── profile_dft-road-casualty-statistics-casualty-2019_20260113_143100.json
    └── README.md  # Document profiling history
```

## Examples

### Example 1: Profile for Staging Model Creation

```bash
# Step 1: Profile source table
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table raw_customers --verbose

# Review output
# - PK: customer_id (100% distinct, 0% null)
# - Nulls: phone_number (10%), secondary_email (76%)
# - Categorical: status (3 values: Active, Inactive, Pending)

# Step 2: Create staging model
# models/staging/erp/stg_erp__customers.sql

# Step 3: Add tests from recommendations
# models/staging/erp/_stg_erp__schema.yml
```

### Example 2: Batch Profile All Sources

```bash
# Profile all ERP source tables
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --tables \
  raw_customers \
  raw_orders \
  raw_products \
  raw_line_items \
  raw_payments

# Review all profiles to identify:
# - Primary keys for each table
# - Foreign key relationships
# - Data quality issues
# - Test requirements
```

### Example 3: Data Quality Investigation

```bash
# Profile to identify data quality issues
python "${CLAUDE_PLUGIN_ROOT}/skills/data-profiler/scripts/profile_data.py" --table orders --detailed

# Output shows:
# - order_total has negative values (data quality issue)
# - ship_date is null for 5% of orders
# - customer_id has values not in customers table (referential integrity issue)

# Fix issues at source or handle in staging model
```

## Related Skills

- **sql-server-reader**: Ad-hoc queries and table exploration
- **dbt-runner**: Execute dbt models after creation
- **dbt-test-coverage-analyzer**: Validate test coverage

## Related Agents

- **dbt-staging-builder**: Primary consumer of profiling insights
- **business-analyst**: Uses for discovery phase
- **dbt-test-writer**: Uses for test design
- **dbt-dimension-builder**: Uses for SCD analysis

---

**Key Value**: Automates what would require 10-20 manual queries, provides intelligent recommendations, and accelerates staging model development by 70%.
