---
name: fabric-cli-runner
description: Execute Fabric CLI (fab) commands for notebook deployment, execution, and workspace management. Use when deploying notebooks to Fabric, running notebooks, listing workspace items, or managing Fabric resources. Supports authentication, import/export, synchronous job execution, and JSON output.
allowed-tools: Bash Read Glob
---

# Fabric CLI Runner

Execute Fabric CLI (`fab`) commands to deploy, run, and manage notebooks and workspace items in Microsoft Fabric.

## Overview

This skill provides a wrapper for the official Microsoft Fabric CLI (`fab`), enabling agents to:
- Deploy notebooks from local files to Fabric workspaces
- Execute notebooks and wait for completion synchronously
- List and inspect workspace items (notebooks, lakehouses, warehouses)
- Copy files to OneLake (lakehouses)
- Check job status and run history
- Manage workspace resources (delete, export)

This is the Fabric equivalent of the `dbt-runner` skill - it closes the execution loop so agents can deploy and validate their generated notebooks.

## Prerequisites

### Install Fabric CLI

```bash
pip install ms-fabric-cli
```

### System Requirements
- Python 3.10 - 3.13
- Azure authentication (`az login` or service principal)

### Verify Installation

```bash
fab --version
```

## Authentication

### Interactive (Development)

```bash
# Login with browser flow
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" auth login
```

### Service Principal (CI/CD)

Set environment variables:
```env
FABRIC_TENANT_ID=your-tenant-id
FABRIC_CLIENT_ID=your-client-id
FABRIC_CLIENT_SECRET=your-client-secret
```

Then authenticate:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" auth login --tenant FABRIC_TENANT_ID --service-principal --client-id FABRIC_CLIENT_ID --client-secret FABRIC_CLIENT_SECRET
```

## Usage

The skill is invoked through the Python script located in `scripts/run_fabric_cli.py`.

### Deploy a Notebook

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" import MyWorkspace/nb_bronze_customers.Notebook -i "3 - Notebooks/bronze/nb_bronze_customers.py"
```

### Run a Notebook (synchronous)

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run MyWorkspace/nb_bronze_customers.Notebook
```

### Run with Parameters

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run MyWorkspace/nb_bronze_customers.Notebook -P source_path:string=Files/raw/customers.csv
```

### Check Job Status

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run-status MyWorkspace/nb_bronze_customers.Notebook --run-id <run-id>
```

### List Job Runs

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run-list MyWorkspace/nb_bronze_customers.Notebook
```

### List Workspace Items

```bash
# List all items
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace

# List only notebooks
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace --type Notebook

# List only lakehouses
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace --type Lakehouse
```

### Inspect an Item

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" get MyWorkspace/nb_bronze_customers.Notebook
```

### Delete an Item

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" rm MyWorkspace/nb_bronze_customers.Notebook -f
```

### Copy Files to OneLake

```bash
# Upload CSV to lakehouse Files area
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" cp "2 - Source Files/customers.csv" MyWorkspace/lh_bronze.Lakehouse/Files/raw/

# Upload entire folder
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" cp "2 - Source Files/" MyWorkspace/lh_bronze.Lakehouse/Files/raw/ --recursive
```

### Direct API Calls

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" api get /v1/workspaces
```

### List Workspaces

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls
```

## Common Patterns

### Full Deploy-Execute-Validate Workflow

```bash
# 1. Upload source data to OneLake
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" cp "2 - Source Files/customers.csv" MyWorkspace/lh_bronze.Lakehouse/Files/raw/

# 2. Deploy notebook
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" import MyWorkspace/nb_bronze_customers.Notebook -i "3 - Notebooks/bronze/nb_bronze_customers.py"

# 3. Execute notebook (synchronous - waits for completion)
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run MyWorkspace/nb_bronze_customers.Notebook

# 4. Validate with fabric-lakehouse-reader skill
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py" --query "SELECT COUNT(*) FROM bronze_customers"
```

### Bulk Import All Notebooks

For bulk deployment, use the dedicated `fabric-notebook-deployer` skill. It bundles the loop with retry/log/dry-run behavior and produces a structured JSON envelope:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-notebook-deployer/scripts/deploy_notebooks.py" --workspace "MyWorkspace" --pattern "3 - Notebooks/**/*.ipynb"
```

This is preferred over a shell loop because (a) it follows the plugin's atomic-Bash policy (one tool call instead of a `for` loop with `$(...)` substitution), and (b) it provides retry on rate-limit, dry-run mode, and error capture per file.

### Workspace Inspection

```bash
# See all items in workspace
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace

# Get details of specific notebook
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" get MyWorkspace/nb_bronze_customers.Notebook
```

## Output Format

For machine-parseable output, the script automatically adds `--output_format json` to `job` subcommands. For other commands, add it explicitly:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace --output_format json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (general) |
| 2 | Authentication error |
| 4 | Timeout |

## Error Handling

### Authentication Failures

```
ERROR: fab command failed - authentication required
Run: python run_fabric_cli.py auth login
Or set FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET environment variables
```

### Item Not Found

```
ERROR: Item 'MyWorkspace/nb_missing.Notebook' not found
Run: python run_fabric_cli.py ls MyWorkspace --type Notebook
```

### Timeout on Job Execution

```
ERROR: Job execution timed out after 600 seconds
Check status: python run_fabric_cli.py job run-status MyWorkspace/nb_name.Notebook --run-id <id>
```

## Integration with Agents

### fabric-bronze-builder Agent
Deploy and execute generated bronze notebooks:
```bash
# After generating nb_bronze_customers.py
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" import MyWorkspace/nb_bronze_customers.Notebook -i "3 - Notebooks/bronze/nb_bronze_customers.py"
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run MyWorkspace/nb_bronze_customers.Notebook
```

### dbt-pipeline-validator Agent
Verify notebooks are deployed and check run history:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace --type Notebook
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" job run-list MyWorkspace/nb_bronze_customers.Notebook
```

### business-analyst Agent
Explore workspace contents during discovery:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls MyWorkspace --type Lakehouse
```

## Requirements

### Python Dependencies
- `ms-fabric-cli` - Official Microsoft Fabric CLI

### Installation
```bash
pip install ms-fabric-cli
```

### Azure Authentication
```bash
# Interactive login
az login

# Or install Azure CLI: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
```

## Configuration

### Project Config Auto-Discovery

The script automatically searches for `project-config.yml` in the current directory and parent directories. If found, it prints the configured workspace name as context (but does not auto-inject it into commands).

### Environment Variables (Optional)
```env
FABRIC_TENANT_ID=your-tenant-id
FABRIC_CLIENT_ID=your-client-id
FABRIC_CLIENT_SECRET=your-client-secret
```

## Troubleshooting

### fab Not Found
```bash
# Install Fabric CLI
pip install ms-fabric-cli

# Verify installation
fab --version
```

### Authentication Required
```bash
# Interactive login
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" auth login

# Check current auth status
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" auth status
```

### Workspace Not Found
```bash
# List all workspaces you have access to
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-cli-runner/scripts/run_fabric_cli.py" ls

# Check workspace name spelling (case-sensitive)
```

### Import Fails
```bash
# Verify source file exists
ls "3 - Notebooks/bronze/nb_bronze_customers.py"

# Verify item type suffix (.Notebook, .Lakehouse, etc.)
# Common types: .Notebook, .Lakehouse, .Warehouse, .SemanticModel
```

## Best Practices

### Deployment
- Always use explicit workspace/item paths (don't rely on defaults)
- Use `.Notebook` suffix for notebook items
- Verify deployment with `fab ls` after import
- Keep local notebooks as the source of truth (re-import to update)

### Execution
- Use synchronous `job run` (default) for pipeline workflows
- Check exit code to determine success/failure
- Review job run history for debugging failures

### Security
- Never commit credentials to git
- Use `az login` for development, service principal for CI/CD
- Service principal credentials passed via env vars only
- `.gitignore` already excludes `.env` files

### Performance
- Batch imports with shell loops for bulk deployment
- Use `--type` filter with `ls` to reduce output
- Use `--output_format json` for machine parsing in scripts
