#!/usr/bin/env python3
"""
Fabric Project Initializer Script

Creates a Microsoft Fabric data engineering project structure with:
- Numbered folder hierarchy (0-7)
- Medallion architecture notebook folders (bronze/silver/gold)
- Utility notebook templates
- Project configuration for workspace/lakehouse
- CLAUDE.md for agentic development

Usage:
    python initialize_fabric_project.py --target "C:\\path\\to\\project"
    python initialize_fabric_project.py --target "C:\\path\\to\\project" --name "my_project" --workspace "Dev"

Author: Claude Code
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


def sanitize_name(name: str) -> str:
    """Convert project name to valid identifier (lowercase, underscores)."""
    sanitized = re.sub(r'[\s\-]+', '_', name.lower())
    sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)
    if sanitized and sanitized[0].isdigit():
        sanitized = 'project_' + sanitized
    return sanitized or 'fabric_project'


def get_display_name(sanitized_name: str) -> str:
    """Convert sanitized name back to display format (Title Case)."""
    return ' '.join(word.capitalize() for word in sanitized_name.split('_'))


def prompt_for_value(prompt: str, default: str = None) -> str:
    """Prompt user for input with optional default."""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        while True:
            user_input = input(f"{prompt}: ").strip()
            if user_input:
                return user_input
            print("  This field is required. Please enter a value.")


def create_folder_structure(target_path: Path) -> dict:
    """Create the numbered folder structure with notebook sub-folders."""
    folders = {
        "0 - Architecture Setup": "Project configuration and setup",
        "1 - Documentation": "Project documentation and requirements",
        "2 - Source Files": "Source data and external files",
        "3 - Notebooks": "PySpark notebooks by medallion layer",
        "6 - Agentic Resources": "Reference materials and patterns",
    }

    created = {}
    for folder, description in folders.items():
        folder_path = target_path / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        created[folder] = str(folder_path)
        print(f"  Created: {folder}")

    # Create notebook sub-folders
    notebooks_path = target_path / "3 - Notebooks"
    notebook_layers = ["bronze", "silver", "gold", "utilities", "orchestration"]
    for layer in notebook_layers:
        layer_path = notebooks_path / layer
        layer_path.mkdir(parents=True, exist_ok=True)
        # Create .gitkeep for empty folders
        (layer_path / ".gitkeep").touch()
    print("  Created: 3 - Notebooks/{bronze,silver,gold,utilities,orchestration}")

    # Create data-profiles sub-folder
    (target_path / "1 - Documentation" / "data-profiles").mkdir(parents=True, exist_ok=True)
    print("  Created: 1 - Documentation/data-profiles/")

    return created


def create_utility_notebook(target_path: Path, config: dict) -> None:
    """Create starter utility notebook in 3 - Notebooks/utilities/."""
    utility_content = f'''# Notebook: nb_utils_config
# Purpose: Shared configuration and utility functions for {config["display_name"]}
# Usage: %run utilities/nb_utils_config

# --- Project Configuration ---
PROJECT_NAME = "{config["display_name"]}"
WORKSPACE = "{config["workspace"]}"

# Lakehouse names
BRONZE_LAKEHOUSE = "{config["bronze_lakehouse"]}"
SILVER_LAKEHOUSE = "{config["silver_lakehouse"]}"
GOLD_LAKEHOUSE = "{config["gold_lakehouse"]}"

# --- Table Naming Functions ---
def bronze_table(source_name: str) -> str:
    """Generate bronze table name."""
    return f"bronze_{{source_name}}"

def silver_table(entity_name: str) -> str:
    """Generate silver table name."""
    return f"silver_{{entity_name}}"

def dim_table(entity_name: str) -> str:
    """Generate dimension table name."""
    return f"dim_{{entity_name}}"

def fct_table(process_name: str) -> str:
    """Generate fact table name."""
    return f"fct_{{process_name}}"

# --- Metadata Column Functions ---
from pyspark.sql import functions as F

def add_bronze_metadata(df):
    """Add standard bronze metadata columns to a DataFrame."""
    return df \\
        .withColumn("_load_timestamp", F.current_timestamp()) \\
        .withColumn("_source_file", F.input_file_name()) \\
        .withColumn("_load_id", F.lit(
            notebookutils.runtime.context.get("currentRunId", "manual")
        ))

# --- Validation Functions ---
def validate_row_count(table_name: str, min_rows: int = 1):
    """Validate that a table has at least min_rows."""
    count = spark.table(table_name).count()
    assert count >= min_rows, f"FAIL: {{table_name}} has {{count}} rows (min: {{min_rows}})"
    print(f"PASS: {{table_name}} has {{count}} rows")
    return count

def validate_no_nulls(table_name: str, columns: list):
    """Validate that specified columns have no null values."""
    df = spark.table(table_name)
    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        assert null_count == 0, f"FAIL: {{col_name}} in {{table_name}} has {{null_count}} nulls"
        print(f"PASS: {{col_name}} has 0 nulls")

def validate_unique(table_name: str, columns: list):
    """Validate that specified columns form a unique key."""
    df = spark.table(table_name)
    total = df.count()
    distinct = df.select(columns).distinct().count()
    dups = total - distinct
    assert dups == 0, f"FAIL: {{dups}} duplicate rows on {{columns}} in {{table_name}}"
    print(f"PASS: {{columns}} unique in {{table_name}} ({{total}} rows)")

print(f"Configuration loaded for: {{PROJECT_NAME}}")
print(f"Workspace: {{WORKSPACE}}")
print(f"Lakehouses: {{BRONZE_LAKEHOUSE}} / {{SILVER_LAKEHOUSE}} / {{GOLD_LAKEHOUSE}}")
'''

    utility_path = target_path / "3 - Notebooks" / "utilities" / "nb_utils_config.py"
    utility_path.write_text(utility_content, encoding='utf-8')
    print("  Created: 3 - Notebooks/utilities/nb_utils_config.py")


def create_agentic_resources(agentic_path: Path, source_reference_path: Path) -> None:
    """Create agentic resources folder and copy Fabric reference materials."""
    reference_path = agentic_path / "reference"
    reference_path.mkdir(parents=True, exist_ok=True)

    if source_reference_path.exists():
        for item in source_reference_path.iterdir():
            dest = reference_path / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        print(f"  Copied Fabric reference materials from: {source_reference_path}")
    else:
        print(f"  Warning: Fabric reference materials not found at: {source_reference_path}")
        (reference_path / "pyspark-style-guide.md").write_text(
            "# PySpark Style Guide\n\nSee Agents/reference/fabric/ for the full guide.\n"
        )
        (reference_path / "notebook-template.md").write_text(
            "# Notebook Template\n\nSee Agents/reference/fabric/ for the full template.\n"
        )


def generate_project_config_yml(config: dict) -> str:
    """Generate project-config.yml content for Fabric projects."""
    return f"""# Fabric Project Configuration
# Generated by fabric-project-initializer skill

project:
  name: "{config["display_name"]}"
  description: "{config["description"]}"
  type: "fabric"
  created: "{datetime.now().strftime('%Y-%m-%d')}"

fabric:
  workspace: "{config["workspace"]}"
  lakehouses:
    bronze: "{config["bronze_lakehouse"]}"
    silver: "{config["silver_lakehouse"]}"
    gold: "{config["gold_lakehouse"]}"

medallion:
  layers:
    bronze:
      lakehouse: "{config["bronze_lakehouse"]}"
      purpose: "Raw data ingestion (append-only)"
      table_prefix: "bronze_"
      schema_evolution: true
      v_order: false
    silver:
      lakehouse: "{config["silver_lakehouse"]}"
      purpose: "Cleaned and conformed data"
      table_prefix: "silver_"
      schema_evolution: false
      v_order: false
    gold:
      lakehouse: "{config["gold_lakehouse"]}"
      purpose: "Business-ready dimensions and facts"
      table_prefix: "dim_ / fct_"
      schema_evolution: false
      v_order: true

notebooks:
  folder: "3 - Notebooks"
  naming:
    bronze: "nb_bronze_{{source}}.py"
    silver: "nb_silver_{{entity}}.py"
    gold_dim: "nb_gold_dim_{{entity}}.py"
    gold_fact: "nb_gold_fct_{{process}}.py"
    orchestration: "nb_orch_{{pipeline}}.py"
    utility: "nb_utils_{{purpose}}.py"

source_data:
  folder: "2 - Source Files"
"""


def generate_architecture_readme(config: dict) -> str:
    """Generate README.md for Architecture Setup folder."""
    return f"""# Architecture Setup - {config["display_name"]}

Project configuration for Microsoft Fabric medallion architecture.

## Fabric Configuration

| Setting | Value |
|---------|-------|
| Workspace | {config["workspace"]} |
| Bronze Lakehouse | {config["bronze_lakehouse"]} |
| Silver Lakehouse | {config["silver_lakehouse"]} |
| Gold Lakehouse | {config["gold_lakehouse"]} |

## Project Structure

```
{config["display_name"]}/
├── 0 - Architecture Setup/     # This folder
├── 1 - Documentation/          # Project docs, data profiles
├── 2 - Source Files/           # CSV/Parquet source data
├── 3 - Notebooks/
│   ├── bronze/                 # Raw ingestion notebooks
│   ├── silver/                 # Cleaning/transform notebooks
│   ├── gold/                   # Dimension/fact notebooks
│   ├── utilities/              # Shared functions
│   └── orchestration/          # Pipeline DAG notebooks
└── 6 - Agentic Resources/      # Reference materials
```

## Getting Started

1. Upload source files to `2 - Source Files/`
2. Import notebooks from `3 - Notebooks/` to Fabric workspace
3. Attach lakehouses to notebooks in Fabric UI
4. Run bronze notebooks to ingest data
5. Build silver and gold layers iteratively

## Notebook Naming

| Layer | Pattern | Example |
|-------|---------|---------|
| Bronze | `nb_bronze_<source>.py` | `nb_bronze_customers.py` |
| Silver | `nb_silver_<entity>.py` | `nb_silver_customers.py` |
| Gold | `nb_gold_dim_<entity>.py` | `nb_gold_dim_customer.py` |
| Gold | `nb_gold_fct_<process>.py` | `nb_gold_fct_sales.py` |
| Orchestration | `nb_orch_<pipeline>.py` | `nb_orch_daily_load.py` |
| Utility | `nb_utils_<purpose>.py` | `nb_utils_config.py` |

## Table Naming

| Layer | Pattern | Example |
|-------|---------|---------|
| Bronze | `bronze_<source>` | `bronze_customers` |
| Silver | `silver_<entity>` | `silver_customers` |
| Gold | `dim_<entity>` | `dim_customer` |
| Gold | `fct_<process>` | `fct_sales` |
"""


def generate_gitignore() -> str:
    """Generate .gitignore content for Fabric projects."""
    return """# Python
__pycache__/
*.py[cod]
*$py.class
.Python
*.egg-info/
.eggs/
*.egg

# Jupyter / Fabric Notebooks
.ipynb_checkpoints/
*.ipynb_checkpoints

# Fabric / Lakehouse
.lakehouse/
.platform
*.abf

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
desktop.ini

# Environment and credentials
.env
*.pem
*.key
credentials.json

# Project specific
7 - Data Exports/*.csv
7 - Data Exports/*.json

# Claude Code temporary files
tmpclaude-*-cwd
nul

# Claude Code local settings (personal preferences)
.claude/settings.local.json

# Power BI local cache
**/.pbi/cache.abf
"""


def generate_claude_md(config: dict, template_path: Path = None) -> str:
    """Generate CLAUDE.md content from template file."""
    if template_path is None:
        script_dir = Path(__file__).parent
        template_path = script_dir.parent / "templates" / "fabric-CLAUDE.md"

    if not template_path.exists():
        print()
        print("ERROR: Template file not found!")
        print(f"  Expected: {template_path}")
        print()
        print("The template file is required to generate CLAUDE.md.")
        print("Ensure the skill folder contains: templates/fabric-CLAUDE.md")
        print()
        raise FileNotFoundError(f"Required template not found: {template_path}")

    template_content = template_path.read_text(encoding='utf-8')

    replacements = {
        "{{PROJECT_DISPLAY_NAME}}": config["display_name"],
        "{{CREATED_DATE}}": datetime.now().strftime('%Y-%m-%d'),
        "{{PROJECT_DESCRIPTION}}": config["description"],
        "{{WORKSPACE_NAME}}": config["workspace"],
        "{{BRONZE_LAKEHOUSE}}": config["bronze_lakehouse"],
        "{{SILVER_LAKEHOUSE}}": config["silver_lakehouse"],
        "{{GOLD_LAKEHOUSE}}": config["gold_lakehouse"],
    }

    result = template_content
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    return result


def generate_settings_local_json() -> str:
    """Generate .claude/settings.local.json with minimum safe defaults.

    Focused on what's actually needed during data pipeline builds:
    - All SQL Server MCP read-only tools (metadata discovery is constant)
    - SQL query execution (needed by agents, profiler, and reader skills)
    - Skills auto-allowed
    - Git read-only operations (used constantly by agents)
    - Python execution (needed for skill scripts)
    - Temp file cleanup

    Bash file operations (cat, ls, grep, etc.) are NOT included because
    Claude Code has dedicated Read/Glob/Grep tools that are always allowed.
    """
    settings = {
        "permissions": {
            "allow": [
                # Skills - auto-allow all skill executions
                "Skill",

                # MCP SQL Server - all read-only metadata tools
                "mcp__local-sql-server-mcp__get_databases",
                "mcp__local-sql-server-mcp__get_current_database",
                "mcp__local-sql-server-mcp__use_database",
                "mcp__local-sql-server-mcp__get_tables",
                "mcp__local-sql-server-mcp__get_table_schema",
                "mcp__local-sql-server-mcp__get_views",
                "mcp__local-sql-server-mcp__get_view_definition",

                # MCP SQL Server - query execution (SELECT only by tool design)
                "mcp__local-sql-server-mcp__execute_query",

                # Git read-only operations (used constantly by agents)
                "Bash(git status:*)",
                "Bash(git log:*)",
                "Bash(git diff:*)",
                "Bash(git branch:*)",
                "Bash(git show:*)",

                # Python execution (needed for skill scripts: profiler, executor, reader)
                "Bash(python:*)",
                "Bash(py:*)",

                # Temp file cleanup (narrow patterns, safe)
                "Bash(rm tmpclaude-*)",
                "Bash(rm nul)",
            ]
        }
    }
    return json.dumps(settings, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Initialize a new Microsoft Fabric data engineering project"
    )
    parser.add_argument(
        "--target", "-t",
        type=str,
        required=True,
        help="Target directory for the new project"
    )
    parser.add_argument(
        "--name", "-n",
        type=str,
        help="Project name (will be sanitized)"
    )
    parser.add_argument(
        "--workspace", "-w",
        type=str,
        help="Fabric workspace name"
    )
    parser.add_argument(
        "--bronze-lakehouse",
        type=str,
        default="lh_bronze",
        help="Bronze lakehouse name (default: lh_bronze)"
    )
    parser.add_argument(
        "--silver-lakehouse",
        type=str,
        default="lh_silver",
        help="Silver lakehouse name (default: lh_silver)"
    )
    parser.add_argument(
        "--gold-lakehouse",
        type=str,
        default="lh_gold",
        help="Gold lakehouse name (default: lh_gold)"
    )
    parser.add_argument(
        "--description",
        type=str,
        help="Project description"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force initialization even if target directory is not empty"
    )

    args = parser.parse_args()

    target_path = Path(args.target).resolve()

    print("=" * 60)
    print("Fabric Project Initializer")
    print("=" * 60)
    print()

    # Interactive prompts if values not provided
    if not args.name:
        args.name = prompt_for_value("Project name (e.g., 'Sales Analytics')")

    if not args.workspace:
        args.workspace = prompt_for_value("Fabric workspace name", default="Development")

    if not args.description:
        args.description = prompt_for_value(
            "Project description",
            default=f"Fabric data engineering project for {args.name}"
        )

    # Sanitize project name
    project_name = sanitize_name(args.name)
    display_name = get_display_name(project_name)

    config = {
        "project_name": project_name,
        "display_name": display_name,
        "workspace": args.workspace,
        "bronze_lakehouse": args.bronze_lakehouse,
        "silver_lakehouse": args.silver_lakehouse,
        "gold_lakehouse": args.gold_lakehouse,
        "description": args.description,
    }

    print()
    print("Configuration:")
    print(f"  Target: {target_path}")
    print(f"  Project Name: {display_name} ({project_name})")
    print(f"  Workspace: {config['workspace']}")
    print(f"  Bronze Lakehouse: {config['bronze_lakehouse']}")
    print(f"  Silver Lakehouse: {config['silver_lakehouse']}")
    print(f"  Gold Lakehouse: {config['gold_lakehouse']}")
    print(f"  Description: {config['description']}")
    print()

    # Check if target exists
    if target_path.exists() and any(target_path.iterdir()):
        if args.force:
            print(f"Warning: Target directory is not empty: {target_path}")
            print("  Continuing anyway (--force flag specified)")
        else:
            print(f"Warning: Target directory is not empty: {target_path}")
            response = input("Continue anyway? (y/N): ").strip().lower()
            if response != 'y':
                print("Aborted.")
                return 1

    # Create target directory
    target_path.mkdir(parents=True, exist_ok=True)

    # Step 1: Create folder structure
    print("Creating folder structure...")
    create_folder_structure(target_path)

    # Step 2: Create utility notebooks
    print("\nCreating utility notebooks...")
    create_utility_notebook(target_path, config)

    # Step 3: Create agentic resources (copy Fabric reference materials)
    print("\nCreating agentic resources...")
    agentic_path = target_path / "6 - Agentic Resources"
    # Resolution order:
    #   1) CLAUDE_PLUGIN_ROOT/reference (when this script is bundled in the
    #      fabric-dataflow-migration-toolkit plugin)
    #   2) ../../../Agents/reference/fabric (legacy standalone-skill layout)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        source_reference = Path(plugin_root) / "reference"
    else:
        script_dir = Path(__file__).parent
        source_reference = script_dir.parent.parent.parent / "Agents" / "reference" / "fabric"
    create_agentic_resources(agentic_path, source_reference)

    # Step 4: Generate configuration files
    print("\nGenerating configuration files...")

    # project-config.yml
    arch_setup_path = target_path / "0 - Architecture Setup"
    (arch_setup_path / "project-config.yml").write_text(
        generate_project_config_yml(config), encoding='utf-8'
    )
    print("  Created: 0 - Architecture Setup/project-config.yml")

    # README.md
    (arch_setup_path / "README.md").write_text(
        generate_architecture_readme(config), encoding='utf-8'
    )
    print("  Created: 0 - Architecture Setup/README.md")

    # .gitignore
    (target_path / ".gitignore").write_text(generate_gitignore(), encoding='utf-8')
    print("  Created: .gitignore")

    # CLAUDE.md
    (target_path / "CLAUDE.md").write_text(generate_claude_md(config), encoding='utf-8')
    print("  Created: CLAUDE.md")

    # .claude/settings.local.json
    claude_dir = target_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.local.json").write_text(generate_settings_local_json(), encoding='utf-8')
    print("  Created: .claude/settings.local.json (auto-allows skills and safe operations)")

    # Summary
    print()
    print("=" * 60)
    print("Fabric Project Initialization Complete!")
    print("=" * 60)
    print()
    print(f"Project created at: {target_path}")
    print()
    print("Next steps:")
    print("  1. Upload source data to '2 - Source Files/'")
    print("  2. Use fabric-bronze-builder agent to create ingestion notebooks")
    print("  3. Import notebooks from '3 - Notebooks/' to Fabric workspace")
    print("  4. Attach lakehouses to notebooks in Fabric UI")
    print("  5. Run notebooks to build your medallion pipeline!")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
