---
name: fabric-project-initializer
description: Initialize a Microsoft Fabric data engineering project with medallion architecture folder structure, PySpark notebook templates, lakehouse configuration, and CLAUDE.md for agentic development. Use when starting a new Fabric analytics project or scaffolding a medallion lakehouse pipeline.
allowed-tools: Bash Read Write Edit Glob
---

# Fabric Project Initializer

Initialize a complete Microsoft Fabric data engineering project with medallion architecture, PySpark notebook templates, and agentic development configuration.

## Overview

This skill creates a fully configured project structure for Microsoft Fabric + Power BI development workflows. It sets up:
- Numbered folder structure (0-7) for organized development
- Notebook sub-folders by medallion layer (bronze/silver/gold)
- Utility notebook templates for shared functions
- project-config.yml with workspace and lakehouse configuration
- CLAUDE.md customized for Fabric agent orchestration
- Reference materials for Fabric agents

**Key difference from `project-initializer`:** No dbt project, no virtual environment. Fabric manages the Spark runtime. This skill focuses on folder structure, configuration, and notebook templates.

## Usage

### Interactive Mode (Recommended)

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-project-initializer/scripts/initialize_fabric_project.py" --target "C:\path\to\new\project"
```

The script will prompt for:
- **Project name**: Used for folder name and configuration
- **Workspace name**: Fabric workspace name
- **Description**: Brief project description

### Non-Interactive Mode

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-project-initializer/scripts/initialize_fabric_project.py" \
  --target "C:\path\to\new\project" \
  --name "sales_analytics" \
  --workspace "Analytics Dev" \
  --bronze-lakehouse "lh_bronze" \
  --silver-lakehouse "lh_silver" \
  --gold-lakehouse "lh_gold" \
  --description "Sales analytics medallion pipeline" \
  --force
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--target` | Yes | - | Target directory for the new project |
| `--name` | No | Prompted | Project name (will be sanitized) |
| `--workspace` | No | Prompted | Fabric workspace name |
| `--bronze-lakehouse` | No | `lh_bronze` | Bronze lakehouse name |
| `--silver-lakehouse` | No | `lh_silver` | Silver lakehouse name |
| `--gold-lakehouse` | No | `lh_gold` | Gold lakehouse name |
| `--description` | No | Prompted | Project description |
| `--force`, `-f` | No | False | Force initialization if target not empty |

## What Gets Created

```
ProjectName/
├── 0 - Architecture Setup/
│   ├── project-config.yml          # Fabric project configuration
│   └── README.md                   # Setup documentation
├── 1 - Documentation/              # Project docs, data profiles
│   └── data-profiles/              # Data profiling results
├── 2 - Source Files/               # Source data / external files
├── 3 - Notebooks/
│   ├── bronze/                     # Bronze layer notebooks
│   ├── silver/                     # Silver layer notebooks
│   ├── gold/                       # Gold layer notebooks
│   ├── utilities/                  # Shared utility notebooks
│   │   └── nb_utils_config.py      # Configuration utility template
│   └── orchestration/              # Pipeline orchestration notebooks
├── 4 - Semantic Layer/             # Power BI TMDL
├── 5 - Report Building/            # Power BI reports
├── 6 - Agentic Resources/
│   └── reference/                  # Copied Fabric reference materials
│       ├── pyspark-style-guide.md
│       ├── notebook-template.md
│       ├── delta-lake-patterns.md
│       ├── fabric-testing-patterns.md
│       └── examples/
├── 7 - Data Exports/               # Query results
├── .gitignore                      # Fabric-specific ignore patterns
└── CLAUDE.md                       # Project-specific agent config
```

## Post-Initialization Steps

1. **Upload to Fabric workspace**: Import notebooks from `3 - Notebooks/` into your Fabric workspace
2. **Attach lakehouses**: Connect bronze/silver/gold lakehouses to notebooks
3. **Upload source data**: Place source files in `2 - Source Files/` or upload to lakehouse Files
4. **Start development**: Use `fabric-bronze-builder` agent to create ingestion notebooks

## Integration with Agents

The generated CLAUDE.md configures the project for these agents:

| Agent | Purpose | Status |
|-------|---------|--------|
| fabric-project-setup | Initialize project structure | Available |
| fabric-bronze-builder | Create bronze ingestion notebooks | Available |
| fabric-silver-builder | Create silver transformation notebooks | Coming (Phase 2) |
| fabric-dimension-builder | Create gold dimension notebooks | Coming (Phase 3) |
| fabric-fact-builder | Create gold fact notebooks | Coming (Phase 3) |

## Differences from dbt Project Initializer

| Feature | dbt (`project-initializer`) | Fabric (`fabric-project-initializer`) |
|---------|----------------------------|--------------------------------------|
| Pipeline folder | `3 - Data Pipeline/` (dbt project) | `3 - Notebooks/` (PySpark notebooks) |
| Sub-folders | `models/staging/intermediate/marts` | `bronze/silver/gold/utilities/orchestration` |
| Configuration | dbt_project.yml + profiles.yml | project-config.yml |
| Runtime | Python venv with dbt | Fabric Spark (managed) |
| Database config | SQL Server connection | Workspace + Lakehouse names |
| Setup script | setup_environment.ps1 | Not needed (Fabric manages runtime) |

## Related Skills

- **project-initializer**: dbt + SQL Server project setup (use for dbt projects)
- **tmdl-scaffold**: Initialize Power BI semantic models (works with both dbt and Fabric)
