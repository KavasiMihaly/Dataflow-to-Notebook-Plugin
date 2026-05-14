---
name: dataflow-gen1-extractor
description: >
  Extract Dataflow Gen1 (Power BI Dataflows) definitions from a Fabric/Power BI workspace
  and parse them into individual M query (.pq) files. Use when the user wants to: (1) export
  dataflow definitions from a Power BI workspace, (2) extract M code / Power Query code from
  Dataflow Gen1, (3) migrate Dataflow Gen1 to notebooks or Dataflow Gen2, (4) inventory all
  queries in a workspace's dataflows, (5) parse exported dataflow JSON files into .pq files.
  Triggers on mentions of "dataflow gen1", "export dataflow", "extract M code from dataflow",
  "dataflow migration", "Power BI dataflow export".
---

# Dataflow Gen1 Extractor

Extract all Dataflow Gen1 definitions from a Power BI workspace and parse them into individual M query files with classification metadata.

## Two-Step Process

### Step 1: Export (PowerShell - user runs manually)

Generate `Export-AllDataflows.ps1` from the template, substituting the workspace ID:

```
python scripts/generate_export_script.py --workspace-id "<WORKSPACE_ID>" --output "<TARGET_DIR>/Export-AllDataflows.ps1"
```

The user must run this script manually in PowerShell (requires interactive browser auth via `Connect-PowerBIServiceAccount`).

**Outputs:** `{json_dir}/*.json` + `{json_dir}/dataflow_manifest.csv`

### Step 2: Parse (Python - can run non-interactively)

Extract M queries from the exported JSON files:

```
python scripts/extract_m_from_json.py --source "<JSON_DIR>" --output "<OUTPUT_DIR>" --inventory "<INVENTORY_CSV_PATH>"
```

**Outputs:**
- `{output_dir}/{dataflow_name}/*.pq` (one .pq file per query)
- `{inventory_csv}` with columns: dataflow_name, query_name, file_path, line_count, starts_with_let, source_type, role, extraction_method

### Parameters

| Parameter | Step | Required | Description |
|-----------|------|----------|-------------|
| `--workspace-id` | 1 | Yes | Power BI workspace GUID |
| `--output` | 1 | Yes | Path for generated .ps1 script |
| `--json-dir` | 1 | No | Override JSON output directory in generated script (default: same as script location) |
| `--source` | 2 | Yes | Directory containing exported JSON files |
| `--output` | 2 | Yes | Directory for extracted .pq files |
| `--inventory` | 2 | No | Path for query_inventory.csv (default: `{output}/query_inventory.csv`) |

## JSON Format Details

See [references/json-formats.md](references/json-formats.md) for the 4 known JSON structures from `Export-PowerBIDataflow`.

## Query Classification

The parser auto-classifies each query:

**Source types:** sql_server, analysis_services, sharepoint, excel, csv, web, odata, azure_storage, linked_dataflow, static_table, json, derived

**Roles:** output_entity (loaded to storage), staging (referenced by others), transformation (no direct source), parameter_or_function, helper

## Prerequisites

- PowerShell 5.1+ with `MicrosoftPowerBIMgmt` module
- Python 3.10+ (standard library only - no pip installs needed)
- User must have workspace access (Contributor or higher)
