---
name: fabric-lakehouse-reader
description: Query Fabric lakehouse SQL analytics endpoints with read-only access. Validate data after notebook execution, inspect table schemas, run row count checks, and export results to CSV. Use when validating pipeline output, debugging data issues, or exporting query results from Fabric lakehouses. Requires ODBC Driver 18 and Azure authentication.
allowed-tools: Bash Read Glob
---

# Fabric Lakehouse Reader

Query Fabric lakehouse SQL analytics endpoints to inspect metadata and validate data for pipeline development.

## Overview

This skill provides read-only access to Fabric lakehouse tables via the SQL analytics endpoint, enabling agents to:
- List available tables in the lakehouse
- Inspect table schemas and column definitions
- Execute SELECT queries and export results as CSV
- Validate data after notebook execution
- Debug data issues and inspect sample records

All query results are automatically saved to `7 - Data Exports/` as CSV files.

This is the Fabric equivalent of the `sql-server-reader` skill.

## Connection Details

- **Endpoint**: Fabric SQL analytics endpoint (e.g., `xxx.datawarehouse.fabric.microsoft.com`)
- **Database**: Lakehouse name (e.g., `lh_bronze`)
- **Authentication**: Entra ID (Azure AD) - `az login` or service principal
- **Driver**: ODBC Driver 18 for SQL Server
- **Mode**: Read-only (SELECT statements only)

## Prerequisites

### Python Dependencies

```bash
pip install pyodbc pandas azure-identity
```

### ODBC Driver 18

Windows users: Download from [Microsoft ODBC Driver](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

**Verify driver**:
```bash
python -c "import pyodbc; print([d for d in pyodbc.drivers() if '18' in d])"
```

### Azure Authentication

```bash
# Interactive login (development)
az login

# Or install Azure CLI: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
```

## Usage

The skill is invoked through the Python script located in `scripts/query_fabric_lakehouse.py`.

### Test Connection

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --test-connection --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

### List All Tables

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

**Output**: Displays table names and saves list to `7 - Data Exports/table_list.csv`

### Get Schema for a Specific Table

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --schema bronze_customers --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

**Output**:
- Column names, data types, nullability
- Saves schema to `7 - Data Exports/schema_bronze_customers.csv`

### Execute a SELECT Query

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT COUNT(*) as row_count FROM bronze_customers" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

**Output**:
- Query results displayed in terminal
- Saves to `7 - Data Exports/query_results_TIMESTAMP.csv`

### Execute Query from File

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query-file path/to/query.sql --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

### Export Specific Table to CSV

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --export bronze_customers --limit 1000 --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

**Output**: Full table export to `7 - Data Exports/bronze_customers_TIMESTAMP.csv`

### Limit Result Rows

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT * FROM bronze_customers" --limit 100 --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

## Authentication Methods

### Azure CLI (Default - Development)

```bash
az login
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

Uses `DefaultAzureCredential` which tries (in order):
1. Environment variables
2. Azure CLI (`az login`)
3. Managed Identity
4. Visual Studio Code credentials

### Service Principal (CI/CD)

Set environment variables:
```env
FABRIC_TENANT_ID=your-tenant-id
FABRIC_CLIENT_ID=your-client-id
FABRIC_CLIENT_SECRET=your-client-secret
```

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze --auth-method service_principal
```

Or pass credentials directly:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze --auth-method service_principal --tenant-id <id> --client-id <id> --client-secret <secret>
```

## Common Patterns

### Post-Notebook Validation Workflow

```bash
# After running bronze notebook, validate the load
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "
SELECT
  COUNT(*) as total_rows,
  COUNT(DISTINCT _load_id) as load_batches,
  MIN(_load_timestamp) as earliest_load,
  MAX(_load_timestamp) as latest_load
FROM bronze_customers
" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

### Row Count Checks

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "
SELECT 'bronze_customers' as table_name, COUNT(*) as rows FROM bronze_customers
UNION ALL
SELECT 'bronze_orders', COUNT(*) FROM bronze_orders
UNION ALL
SELECT 'bronze_products', COUNT(*) FROM bronze_products
" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

### Null Analysis

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "
SELECT
  COUNT(*) as total_rows,
  COUNT(CASE WHEN customer_id IS NULL THEN 1 END) as null_customer_ids,
  COUNT(CASE WHEN email IS NULL THEN 1 END) as null_emails,
  COUNT(CASE WHEN created_date IS NULL THEN 1 END) as null_dates
FROM bronze_customers
" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

### Compare Bronze vs Silver

```bash
# Bronze count
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT COUNT(*) as bronze_rows FROM bronze_customers" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze

# Silver count
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT COUNT(*) as silver_rows FROM silver_customers" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_silver
```

## Safety Features

### Read-Only Mode
- Only SELECT statements permitted
- INSERT, UPDATE, DELETE, DROP blocked
- Query validation before execution
- No DDL operations allowed
- SQL analytics endpoint is inherently read-only (Fabric limitation)

### Query Validation
The script validates queries before execution:
- Allowed: SELECT, WITH (CTEs)
- Blocked: INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, EXECUTE, MERGE

### Result Size Management
- Default limit: 10,000 rows (configurable)
- Large result warnings
- Automatic CSV export for all results

## Limitations

The Fabric SQL analytics endpoint supports a T-SQL subset:
- No stored procedures
- No temporary tables
- No variable declarations
- No control flow (IF/WHILE)
- Read-only (no DML statements)
- Limited function support compared to full SQL Server

## Output Location

All exports are saved to:
```
7 - Data Exports/
├── table_list.csv
├── schema_bronze_customers.csv
├── query_results_20260209_143022.csv
├── bronze_customers_20260209_143045.csv
└── ...
```

**File naming convention**:
- Table lists: `table_list.csv`
- Schemas: `schema_{TABLE_NAME}.csv`
- Query results: `query_results_{TIMESTAMP}.csv`
- Table exports: `{TABLE_NAME}_{TIMESTAMP}.csv`

## Error Handling

The script provides clear error messages for:
- Connection failures
- Authentication errors
- Invalid queries
- Non-existent tables
- Query timeouts
- Missing ODBC driver

**Example errors**:
```
ERROR: Connection failed - authentication required
Run: az login
Then retry the command.
```

```
ERROR: Invalid query - write operations not permitted
Query contained: INSERT INTO
Only SELECT statements are allowed.
```

```
ERROR: ODBC Driver 18 for SQL Server not found
Install from: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
```

## Integration with Agents

### dbt-pipeline-validator Agent
Validate pipeline output after notebook execution:
```bash
# Check row counts across all layers
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT COUNT(*) FROM bronze_customers" --endpoint ... --database lh_bronze

# Inspect schemas
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --schema bronze_customers --endpoint ... --database lh_bronze
```

### business-analyst Agent
Explore data during discovery:
```bash
# What tables exist?
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint ... --database lh_bronze

# Sample data
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT TOP 10 * FROM bronze_customers" --endpoint ... --database lh_bronze
```

### fabric-bronze-builder Agent
Validate bronze load results:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "
SELECT COUNT(*) as rows, COUNT(DISTINCT _load_id) as loads FROM bronze_customers
" --endpoint ... --database lh_bronze
```

## Configuration

### Project Config Auto-Discovery

The script searches for `project-config.yml` in the current directory and parent directories. If found, it reads `sql_endpoint` and `database` fields to use as defaults:

```yaml
# project-config.yml
workspace_name: "MyWorkspace"
sql_endpoint: "xxx.datawarehouse.fabric.microsoft.com"
bronze_lakehouse: "lh_bronze"
silver_lakehouse: "lh_silver"
gold_lakehouse: "lh_gold"
```

When auto-discovered, you can omit `--endpoint` and `--database`:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables
```

### Environment Variables (Optional)
```env
FABRIC_SQL_ENDPOINT=xxx.datawarehouse.fabric.microsoft.com
FABRIC_DATABASE=lh_bronze
FABRIC_TENANT_ID=your-tenant-id
FABRIC_CLIENT_ID=your-client-id
FABRIC_CLIENT_SECRET=your-client-secret
```

### Script Arguments
All connection details can be passed as arguments:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" \
  --endpoint xxx.datawarehouse.fabric.microsoft.com \
  --database lh_bronze \
  --auth-method azure_cli \
  --query "SELECT * FROM bronze_customers"
```

## Troubleshooting

### Connection Refused
```bash
# Test connection
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --test-connection --endpoint ... --database ...

# Verify Azure authentication
az account show
```

### Authentication Failed
- Verify `az login` is current (tokens expire)
- Check you have access to the Fabric workspace
- For service principal: verify tenant/client/secret are correct
- Ensure the identity has at least Viewer role on the lakehouse

### ODBC Driver Not Found
```bash
# Check installed drivers
python -c "import pyodbc; print(pyodbc.drivers())"

# Install ODBC Driver 18 for SQL Server
# https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
```

### Table Not Found
```bash
# List all available tables
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint ... --database ...

# Note: Delta tables may take a moment to appear in SQL endpoint after creation
```

## Best Practices

### Performance
- Use `--limit` for exploratory queries on large tables
- Use WHERE clauses to filter data before export
- Avoid `SELECT *` on wide tables - specify columns
- The SQL analytics endpoint is optimized for analytical queries

### Security
- Never commit credentials to git
- Use `az login` for development, service principal for CI/CD
- Use environment variables for credentials
- `.gitignore` already excludes `.env` files

### Data Exports
- Clean up old CSV files regularly (7 - Data Exports/)
- Use meaningful query filenames with `--output`
- Document complex queries in .sql files
- Add .csv files to .gitignore

### Query Development
1. Start with `--limit 10` for quick validation
2. Use `--verbose` to debug connection issues
3. Save complex queries as .sql files for reuse
4. Use CTEs for readable multi-step queries

## Examples

### Comprehensive data validation workflow

```bash
# 1. List all tables
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze

# 2. Inspect bronze table structure
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --schema bronze_customers --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze

# 3. Export sample data
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --export bronze_customers --limit 1000 --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze

# 4. Check data quality
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "
SELECT
  COUNT(*) as total_rows,
  COUNT(DISTINCT customer_id) as unique_customers,
  COUNT(CASE WHEN email IS NULL THEN 1 END) as null_emails,
  MIN(_load_timestamp) as earliest_load,
  MAX(_load_timestamp) as latest_load
FROM bronze_customers
" --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze

# 5. Find specific issues
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT * FROM bronze_customers WHERE email IS NULL" --output customers_missing_email.csv --endpoint xxx.datawarehouse.fabric.microsoft.com --database lh_bronze
```

### Quick reference guide

```bash
# List tables
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --list-tables --endpoint EP --database DB

# Get schema
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --schema TABLE_NAME --endpoint EP --database DB

# Sample data
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT TOP 10 * FROM TABLE_NAME" --endpoint EP --database DB

# Export full table
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --export TABLE_NAME --endpoint EP --database DB

# Custom query
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "YOUR_SELECT_QUERY" --endpoint EP --database DB

# Query from file
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query-file path/to/query.sql --endpoint EP --database DB

# Test connection
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --test-connection --endpoint EP --database DB
```
