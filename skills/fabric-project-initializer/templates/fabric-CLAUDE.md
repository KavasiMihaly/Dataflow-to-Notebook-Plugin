# {{PROJECT_DISPLAY_NAME}}

**Project Type**: Data Engineering with Microsoft Fabric + PySpark + Power BI
**Created**: {{CREATED_DATE}}
**Description**: {{PROJECT_DESCRIPTION}}

---

## Overview

This project uses the Fabric data engineering agents and skills for building medallion architecture pipelines with PySpark notebooks.

---

## CRITICAL: Agent Orchestration Rules

**YOU MUST DELEGATE TO SPECIALIZED AGENTS. DO NOT BUILD NOTEBOOKS YOURSELF.**

When the user asks to create PySpark notebooks, bronze/silver/gold layers, or data quality checks:

1. **ALWAYS use the Task tool** to invoke the appropriate specialized agent
2. **NEVER write PySpark notebook files directly** - delegate to the agent
3. **NEVER create configuration files directly** - delegate to the agent

### Mandatory Delegation Table

| User Request | YOU MUST USE | DO NOT |
|-------------|--------------|--------|
| "Create bronze notebook for X" | `fabric-bronze-builder` agent via Task tool | Write the notebook yourself |
| "Create silver notebook for X" | `fabric-silver-builder` agent via Task tool | Write the notebook yourself |
| "Create dimension for X" | `fabric-dimension-builder` agent via Task tool | Write the notebook yourself |
| "Create fact table for X" | `fabric-fact-builder` agent via Task tool | Write the notebook yourself |
| Vague requirements | `business-analyst` agent via Task tool | Guess at requirements |

### How to Invoke Agents

Use the Task tool with `subagent_type` matching the agent name:

```
Task tool with:
  subagent_type: "fabric-bronze-builder"
  prompt: "Create bronze notebook for the customers CSV in 2 - Source Files/"
```

### Your Role as Orchestrator

- **You coordinate** - decide which agent to use
- **Agents specialize** - they do the actual notebook building
- **You verify** - check agent results and report to user

**Agents have access to reference materials, PySpark style guides, and testing patterns that ensure consistency. If you build notebooks yourself, you bypass these standards.**

---

## Available Agents

### fabric-bronze-builder
Creates bronze layer PySpark notebooks for raw data ingestion.
```
"Create bronze notebook for the customers CSV"
```

### fabric-silver-builder (Coming - Phase 2)
Creates silver layer notebooks with cleaning, deduplication, and type casting.
```
"Create silver notebook for customer data"
```

### fabric-dimension-builder (Coming - Phase 3)
Creates gold layer dimension notebooks with surrogate keys and SCD patterns.
```
"Create customer dimension with SCD Type 2"
```

### fabric-fact-builder (Coming - Phase 3)
Creates gold layer fact notebooks with dimension lookups and measures.
```
"Create daily sales fact table"
```

### business-analyst
Requirements gathering and technical discovery.
```
"I need better sales reporting" (vague requests)
```

## Available Skills

| Skill | Purpose | Usage |
|-------|---------|-------|
| `fabric-cli-runner` | Deploy and run notebooks | `python run_fabric_cli.py import ...` |
| `fabric-lakehouse-reader` | Validate data in lakehouses | `python query_fabric_lakehouse.py --query ...` |
| `tmdl-scaffold` | Create Power BI TMDL projects | `/tmdl-scaffold` |

## Fabric Configuration

### Workspace
- **Workspace**: {{WORKSPACE_NAME}}

### Lakehouses
| Layer | Lakehouse Name | Purpose |
|-------|---------------|---------|
| Bronze | {{BRONZE_LAKEHOUSE}} | Raw data ingestion (append-only) |
| Silver | {{SILVER_LAKEHOUSE}} | Cleaned and conformed data |
| Gold | {{GOLD_LAKEHOUSE}} | Business-ready dimensions and facts |

### Notebook Naming Conventions
| Layer | Pattern | Example |
|-------|---------|---------|
| Bronze | `nb_bronze_{source}.py` | `nb_bronze_customers.py` |
| Silver | `nb_silver_{entity}.py` | `nb_silver_customers.py` |
| Gold (Dim) | `nb_gold_dim_{entity}.py` | `nb_gold_dim_customer.py` |
| Gold (Fact) | `nb_gold_fct_{process}.py` | `nb_gold_fct_sales.py` |
| Orchestration | `nb_orch_{pipeline}.py` | `nb_orch_daily_load.py` |
| Utility | `nb_utils_{purpose}.py` | `nb_utils_config.py` |

### Table Naming Conventions
| Layer | Pattern | Example |
|-------|---------|---------|
| Bronze | `bronze_{source}` | `bronze_customers` |
| Silver | `silver_{entity}` | `silver_customers` |
| Gold (Dim) | `dim_{entity}` | `dim_customer` |
| Gold (Fact) | `fct_{process}` | `fct_sales` |

## Data Profiles Location

**IMPORTANT**: Data profiles are stored in `1 - Documentation/data-profiles/`

**Always check for existing profiles before creating notebooks:**
```bash
ls "1 - Documentation/data-profiles/"
```

## Project Structure

```
{{PROJECT_DISPLAY_NAME}}/
├── .claude/
│   └── settings.local.json     # Auto-allows skills and safe operations
├── 0 - Architecture Setup/     # Project configuration
│   ├── project-config.yml      # Workspace and lakehouse config
│   └── README.md
├── 1 - Documentation/          # Project docs and architecture
│   └── data-profiles/          # Data profiling results
├── 2 - Source Files/           # CSV/Parquet source data
├── 3 - Notebooks/              # PySpark notebooks
│   ├── bronze/                 # Bronze ingestion notebooks
│   ├── silver/                 # Silver transform notebooks
│   ├── gold/                   # Gold dimension/fact notebooks
│   ├── utilities/              # Shared utility notebooks
│   └── orchestration/          # Pipeline DAG notebooks
├── 4 - Semantic Layer/         # Power BI TMDL files
├── 5 - Report Building/        # .pbip report files
├── 6 - Agentic Resources/      # Agent reference materials
│   └── reference/
├── 7 - Data Exports/           # Query results
└── CLAUDE.md                   # This file
```

## Typical Workflow

1. **Upload source data**: Place CSV/Parquet files in `2 - Source Files/`
2. **Build bronze**: **DELEGATE to `fabric-bronze-builder` agent** (use Task tool)
3. **Build silver**: **DELEGATE to `fabric-silver-builder` agent** (use Task tool)
4. **Build dimensions**: **DELEGATE to `fabric-dimension-builder` agent** (use Task tool)
5. **Build facts**: **DELEGATE to `fabric-fact-builder` agent** (use Task tool)
6. **Deploy notebooks**: Use `fabric-cli-runner` skill to import notebooks to Fabric
7. **Run notebooks**: Use `fabric-cli-runner` skill to execute notebooks
8. **Validate data**: Use `fabric-lakehouse-reader` skill to query and validate results
9. **Create semantic model**: Use `/tmdl-scaffold` skill

**Steps 2-5 REQUIRE agent delegation. Do not write PySpark notebooks directly.**

## Security

- No credentials stored in notebooks or configuration
- Use `notebookutils.credentials.getSecret()` for external source access
- project-config.yml stores workspace/lakehouse names only (no connection strings)
- .gitignore excludes checkpoint files and credentials

## Git Workflow

**IMPORTANT**: Claude Code will NOT create git commits automatically. The user will handle all git operations.

## Repository Maintenance

### Periodic Cleanup Tasks

**Claude Code Temporary Files**:
```bash
rm tmpclaude-*-cwd 2>/dev/null
```

---

*This file serves as the persistent project context and is always loaded into Claude Code conversations. Keep it updated as the project evolves.*
