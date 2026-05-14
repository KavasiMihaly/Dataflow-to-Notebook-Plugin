# Fabric Dataflow Migration Toolkit

> End-to-end Power BI Dataflow Gen1 → Microsoft Fabric medallion notebook migration. Export Gen1 dataflows, analyze M code, generate bronze + silver PySpark notebooks, deploy to Fabric, and validate — in one Claude Code session.

A Claude Code plugin that automates the full Gen1-to-Fabric migration workflow: extract dataflow definitions from a Power BI workspace, analyze every M query for conversion risks, scaffold a medallion lakehouse project, generate `.ipynb` notebooks for bronze and silver layers, deploy via the Fabric CLI, and produce a validation report. Ships with bundled sample dataflows and `--dry-run` support so you can try the full pipeline without a Fabric workspace.

---

## ⚠️ Status: Technology Demonstration & Teaching Tool

**This plugin is primarily a technology demonstration and teaching tool** — built to show how Claude Code plugins can orchestrate a multi-stage data engineering migration end-to-end. It packages a working reference workflow into an installable plugin and applies hard-won lessons from the companion `dbt-pipeline-toolkit` plugin.

**Do NOT use this plugin in production without thorough validation.** Specifically:

- **Review every generated notebook before deployment.** The `m-to-pyspark-converter` produces best-effort drafts; risky patterns (Excel.Workbook, AzureStorage.Blobs, custom M functions, synthetic IDs) are wrapped in `# === HIGH RISK / HUMAN REVIEW REQUIRED ===` isolation cells precisely because they need human judgment.
- **Run against `--sample --dry-run` first**, then a non-production workspace, then a staging workspace, before any production migration.
- **Validate row counts, schemas, and business logic** against the original Dataflow Gen1 outputs. The plugin's validator checks structural shape and basic non-zero rows; it does not verify business correctness.
- **Test refresh schedules and downstream dependencies** (semantic models, reports) before decommissioning the source dataflows.
- **Treat the bundled risk catalog (12+ patterns) as a starting point**, not a guarantee. Unknown M patterns are auto-tracked in `_Documentation/conversion-backlog.md` for follow-up.

The plugin is suitable for: learning the migration pattern, demonstrating agentic data engineering, prototyping Fabric medallion projects, accelerating manual migrations with a strong human-review loop. It is not suitable for unattended production cutover.

---

## Why this plugin

Microsoft [marked Dataflow Gen1 as Legacy in April 2026](https://powerbi.microsoft.com/en-us/blog/dataflows-thank-you-for-eight-years-of-gen1-and-why-gen2-is-the-future/). The official migration paths target **Dataflow Gen2** — but if your target architecture is **Fabric medallion lakehouses + PySpark notebooks** (the recommended pattern for new Fabric workloads), there is no first-party migration path. This plugin fills that gap.

---

## Features

- **6 Agents** — orchestrator, mechanical M analyst, interactive migration analyst, bronze + silver builders, end-to-end validator
- **9 Skills** — Dataflow Gen1 extractor, M-to-PySpark converter, Fabric CLI runner, lakehouse reader, project initializer, data profiler, notebook deployer, pre-flight check, **opt-in pattern-sharing reporter**
- **3 Hooks** — Bash auto-approval for plugin scripts, structural validation, session-start config check
- **Orchestrator-as-main-agent launch** — single `claude --agent ...` invocation drives the full 13-stage pipeline
- **Dry-run mode** — full pipeline without Fabric access, using bundled sample dataflows
- **12 documented M-conversion risk patterns** — best-effort PySpark output with explicit human-review markers
- **Reference materials** — PySpark style guide, notebook templates, Delta Lake patterns, M-to-PySpark mapping, risk catalog

---

## Requirements

Before installing, make sure you have:

- **Claude Code** — CLI, desktop app, or IDE extension
- **Python** `>= 3.10` — for hook scripts and skill scripts
- **PowerShell** `>= 5.1` (Windows) or **PowerShell 7+** (cross-platform) — for Dataflow Gen1 export
  - With `MicrosoftPowerBIMgmt` PowerShell module
- **Microsoft Fabric CLI** — `pip install ms-fabric-cli` (the plugin's pre-flight check verifies this)
- **Azure CLI** — `az login` for interactive auth, OR a service principal with workspace access
- **Power BI workspace access** — Contributor or higher on the source workspace

---

## Installation

### 1. Add the OneDayBI marketplace

```
/plugin marketplace add KavasiMihaly/AI-plugins
```

### 2. Install the plugin

```
/plugin install fabric-dataflow-migration-toolkit@OneDayBI-Marketplace
```

During install you'll be prompted for the `userConfig` values listed below.

### 3. Reload

```
/reload-plugins
```

### 4. Verify

```
/agents             # expect 6 fabric-dataflow-migration-toolkit:* agents
```

---

## Quick start (no Fabric workspace needed)

Try the full pipeline against bundled sample dataflows. From a **fresh shell** (not from inside an existing Claude session), `cd` into an empty working folder and launch the orchestrator as the main agent:

```bash
mkdir ~/fabric-migration-test
cd ~/fabric-migration-test
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate sample dataflows. Flags: --sample --dry-run"
```

This runs every stage except deployment — extracts sample Gen1 JSON, analyzes M queries, generates bronze + silver `.ipynb` notebooks locally, and produces a migration report. Inspect the output before pointing at production.

> **Why launch as the main agent?** The orchestrator delegates to 5 specialist subagents (`m-query-analyst`, `migration-analyst`, `fabric-bronze-builder`, `fabric-silver-builder`, `fabric-pipeline-validator`). Claude Code's hierarchy rules prevent a subagent from spawning further subagents — so the orchestrator must run as the main thread to delegate. Always launch via `claude --agent ...` from a fresh shell, never from inside an existing Claude session.

See [`examples/quickstart.md`](examples/quickstart.md) for a full walkthrough.

---

## Configuration

Prompted on install, editable later via `/plugin`. Sensitive values are stored in your OS keychain.

| Key | Required | Sensitive | Description |
|---|---|---|---|
| `fabric_workspace_id` | yes | no | Target Fabric workspace GUID |
| `fabric_workspace_name` | yes | no | Target Fabric workspace display name |
| `source_workspace_id` | no* | no | Source Power BI workspace GUID (Gen1 dataflows). Optional — set at runtime if missing. |
| `bronze_lakehouse` | no | no | Default `lh_bronze` |
| `silver_lakehouse` | no | no | Default `lh_silver` |
| `gold_lakehouse` | no | no | Default `lh_gold` |
| `azure_tenant_id` | cond. | no | For SP auth |
| `azure_client_id` | cond. | no | For SP auth |
| `azure_client_secret` | cond. | **yes** | For SP auth — keychain-stored |
| `report_unknown_patterns` | no | no | `never` (default) / `ask` / `always` — controls the opt-in pattern-sharing skill (see "Optional: Sharing unknown M patterns" below) |

\* Can be supplied at runtime via the orchestrator's Stage 1 questions.

### Optional: Sharing unknown M patterns

When the `m-query-analyst` encounters an M pattern it doesn't have a reference example for, it auto-records the pattern in `_Documentation/conversion-backlog.md` as `Status: Backlog`. The plugin's risk catalog grows by users sharing these unknown patterns back to the plugin author — but **only with explicit consent**.

The `report-unknown-patterns` skill (opt-in) reads the backlog, sanitizes M snippets to redact connection strings/GUIDs/file paths, shows you a per-pattern preview, and (on per-pattern approval) files a GitHub issue against the plugin repo via the `gh` CLI.

**Three modes via `report_unknown_patterns` userConfig:**

| Value | Behavior |
|---|---|
| `never` (default) | Patterns stay local in `_Documentation/conversion-backlog.md`. The migration-analyst never asks. The skill is never invoked unless you run it manually. **Recommended for sensitive enterprise data.** |
| `ask` | At Stage 5, the migration-analyst asks "share unknowns?" if any unknowns were detected. Your answer is recorded per-run in Section 5 of `migration-design.md`. |
| `always` | Stage 13 auto-invokes the skill (still with sanitization preview + per-pattern approval). Use only if you've reviewed the redaction rules and trust them. |

**To hard-code your decision:**
- During `/plugin install`, set `report_unknown_patterns` to your chosen value
- Or edit `~/.claude/settings.json` under `pluginConfigs[fabric-dataflow-migration-toolkit].options.report_unknown_patterns`
- Or run `/plugin` later and update the value

**Sanitization rules** (full list in `skills/report-unknown-patterns/scripts/report_patterns.py`, four layers):

*Layer 1 — connection PII:*
- Storage URLs (`*.blob.core.windows.net`, `*.dfs.core.windows.net`, `abfss://`, `wasbs://`) → `<REDACTED_URL>`
- Other web URLs → `<REDACTED_URL>`
- SQL connection arguments → `<REDACTED_SERVER>`, `<REDACTED_DB>`
- GUIDs → `<REDACTED_GUID>`
- Quoted file paths (`*.csv`, `*.xlsx`, `*.json`, `*.parquet`, `*.tsv`, `*.txt`) → `<REDACTED_PATH>`
- Excel sheet names → `<REDACTED_SHEET>`

*Layer 2 — schema identifiers:*
- **Column references** `[Column Name]` → `[<REDACTED_COL>]` (record literals like `[Name = expr]` are NOT redacted — those are M syntax for options, not column refs)
- **Quoted identifiers** `#"Step Or Column Name"` → `#"<REDACTED_IDENT>"`

*Layer 3 — string literals (token-aware):*
- All remaining quoted strings with ≥1 word char get redacted to `"<REDACTED_VALUE>"`. This catches column names in `Table.RenameColumns({{"old", "new"}})`, column lists in `Table.SelectColumns({"a", "b"})`, filter values in `each [X] = "Y"`, conditional branches in `each if [X] = "Z" then ...`, and any other quoted business data
- Short strings without word chars (e.g. `","`, `"\n"`, `"\r\n"`) are preserved — these are M syntax delimiters, not data

*Layer 4 — numeric literals:*
- Numbers ≥ 100 (likely filter thresholds, IDs, large constants) → `<REDACTED_NUMBER>`
- Numbers 0-99 preserved — these are typically structural (`Table.Skip(_, 4)`, column index `{0}`)

**Preserved deliberately:** M function names (`Table.SelectRows`, `AzureStorage.Blobs`, etc.) — required to identify the pattern.

Example before/after:

```m
# Before
let
  Source = AzureStorage.Blobs("https://prodstorage.blob.core.windows.net/customers/"),
  #"Filtered rows" = Table.SelectRows(Source, each [Patient ID] = "P-12345"),
  #"Renamed" = Table.RenameColumns(_, {{"DOB", "Date of Birth"}})
in
  #"Renamed"

# After
let
  Source = AzureStorage.Blobs("<REDACTED_URL>/<REDACTED_CONTAINER>/"),
  #"<REDACTED_IDENT>" = Table.SelectRows(Source, each [<REDACTED_COL>] = "<REDACTED_VALUE>"),
  #"<REDACTED_IDENT>" = Table.RenameColumns(_, {{"<REDACTED_VALUE>", "<REDACTED_VALUE>"}})
in
  #"<REDACTED_IDENT>"
```

You see the before/after preview before any `gh issue create` call. Sanitization is best-effort — review carefully. Manual override or skip is always available per pattern.

---

## Usage

### Launching the orchestrator (must be the main agent)

The orchestrator is designed to run as the **main Claude session**, not as a subagent of an existing one. Launch it from a fresh shell via `claude --agent ...`:

```bash
# Full migration with deployment
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows from workspace <GUID>"

# Generate notebooks, skip deployment
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows from workspace <GUID>. Flags: --dry-run"

# Use bundled sample dataflows, no Fabric access needed
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate sample dataflows. Flags: --sample --dry-run"
```

**Do not** try to launch the orchestrator from inside an existing Claude session (e.g. by typing a prompt that asks to spawn the orchestrator via the `Task` tool). The orchestrator delegates to 5 specialist subagents, and Claude Code's hierarchy rules prevent a subagent from spawning further subagents — so it must be the main thread for its delegation to work.

### Agents

| Agent | Role |
|---|---|
| `fabric-migration-orchestrator` | Drives 13-stage pipeline end-to-end |
| `m-query-analyst` | Mechanical M analysis: classify queries, scan risk patterns |
| `migration-analyst` | Interactive: refactor decisions, pattern strategy choices |
| `fabric-bronze-builder` | Generate `nb_bronze_*.ipynb` from output_entity queries |
| `fabric-silver-builder` | Generate `nb_silver_*.ipynb` with `read_bronze()`-only contract |
| `fabric-pipeline-validator` | Validate `.ipynb` JSON, deploy, run, assert row counts |

### Skills

| Skill | Purpose |
|---|---|
| `dataflow-gen1-extractor` | Generate PowerShell + parse JSON exports |
| `m-to-pyspark-converter` | Convert M queries to PySpark drafts |
| `fabric-cli-runner` | Execute `fab` CLI commands |
| `fabric-lakehouse-reader` | Query lakehouse SQL endpoints |
| `fabric-project-initializer` | Scaffold project folders + config |
| `data-profiler` | Profile CSV / source files |
| `fabric-notebook-deployer` | Batch `fab import` deployment |
| `fabric-preflight-check` | Validate fab CLI + auth + workspace before run |
| `report-unknown-patterns` | Opt-in: share unknown M patterns as sanitized GitHub issues (see Configuration section) |

### Hooks

- **PreToolUse Write/Edit** — `validate-fabric-structure.py` enforces `.ipynb` format, `read_bronze()`-only contract, lakehouse binding
- **PreToolUse Bash** — `approve-plugin-bash.py` auto-approves plugin-internal commands (plugin-shipped Python scripts, `fab` CLI, etc.)
- **SessionStart** — `session-start-config-check.py` detects missing config and prints setup banner

---

## Repository layout

```
.claude-plugin/
  └── plugin.json                # Manifest
agents/                          # 6 plugin agents
skills/                          # 8 plugin skills
hooks/                           # 5 hook scripts
reference/                       # PySpark style guide, M conversion catalog, notebook templates
examples/
  ├── sample-dataflows/          # Bundled Gen1 JSON exports for --sample mode
  └── quickstart.md
tests/
  └── validate_notebooks.py      # Pytest-style notebook shape validator
_Documentation/
  ├── plugin_learnings.md        # Fabric-specific findings
  ├── pipeline-workflow.md       # 13-stage process map
  └── conversion-backlog.md      # Unknown M patterns awaiting reference examples
```

---

## Migration workflow (13 stages)

| Stage | Owner | Output |
|---|---|---|
| Pre | `fabric-preflight-check` | Fail fast if auth/CLI missing |
| 0 | Orchestrator | Detect fresh build vs. incremental |
| 1a | Orchestrator | **(Interactive)** If user has no source workspace ID: generate `Discover-AllDataflows.ps1`, user runs it in PowerShell, picks a workspace from the resulting CSV |
| 1b | Orchestrator | **(Interactive)** Workspace + lakehouse config |
| 2 | `dataflow-gen1-extractor` | **(Interactive)** PowerShell export → .pq files |
| 3 | `m-query-analyst` | Inventory + dependency map |
| 4 | `m-query-analyst` | Risk catalog (12 patterns + unknowns) |
| 5 | `migration-analyst` | **(Interactive)** Refactor + strategy decisions |
| 6 | Orchestrator | **(Plan mode)** User approves medallion mapping |
| 7 | `fabric-project-initializer` | Project scaffolding |
| 8 | `fabric-bronze-builder` (parallel) | Bronze `.ipynb` notebooks |
| 9 | `fabric-silver-builder` (canary + parallel) | Silver `.ipynb` notebooks |
| 10 | `fabric-notebook-deployer` | `fab import` (skip in dry-run) |
| 11 | `fabric-cli-runner` | `fab job run` (skip in dry-run) |
| 12 | `fabric-pipeline-validator` | Validate + assert row counts |
| 13 | Orchestrator | Migration report |

Three user touchpoints total (plus an optional one-off discovery step at Stage 1a). Everything else autonomous.

---

## Quality framework

Risky M conversions emit best-effort PySpark in isolated cells with explicit markers:

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Excel.Workbook (RISK-03)
# Original M: Excel.Workbook(File.Contents(...), null, true)
# Best-effort PySpark using pandas + openpyxl:
import pandas as pd
df_pd = pd.read_excel(source_path, sheet_name="Mid-2019 Persons", skiprows=4)
df_raw = spark.createDataFrame(df_pd)
# REVIEW: pandas read serializes large files; consider pre-converting to CSV.
# See: reference/m-conversion-risk-catalog.md#risk-03
# === END HIGH RISK ===
```

Unknown patterns (not in the catalog) get TODO markers AND auto-add to `_Documentation/conversion-backlog.md` for tracking.

Four validation layers:
1. **Pre-build static** — hook validates `.ipynb` shape on every Write
2. **Build conformance gate** — builders return JSON envelope; orchestrator halts on deviations
3. **Post-deployment runtime** — validator queries lakehouses, asserts row counts
4. **End-to-end smoke test** — `tests/validate_notebooks.py` against bundled sample data

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Marketplace not found | Run `/plugin marketplace add` before `/plugin install` |
| `fab` CLI not found | `pip install ms-fabric-cli` (the pre-flight check tells you this) |
| Auth fails | Run `az login` interactively, or set `azure_*` userConfig for SP auth |
| Notebook deploys but cells run as one mega-cell | You shipped `.py` instead of `.ipynb` — the validator should catch this; rebuild |
| `userConfig` prompt didn't fire on install | Edit `~/.claude/settings.json` directly under `pluginConfigs[fabric-dataflow-migration-toolkit].options` |
| Background subagent stalls during notebook generation | Verify `approve-plugin-bash.py` hook fires; Fabric allowlist may need extension |
| Plan-mode gate at Stage 6 doesn't appear | Orchestrator must run as the main thread — launch via `claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "..."` from a fresh shell, not from inside an existing Claude session |

---

## Development

```bash
git clone https://github.com/KavasiMihaly/Dataflow-to-Notebook-Plugin.git
cd Dataflow-to-Notebook-Plugin
```

Point Claude Code at your local checkout:

```
/plugin marketplace add /absolute/path/to/Dataflow-to-Notebook-Plugin
```

After editing agents/skills/hooks, run `/reload-plugins`.

---

## Author

**Mihaly Kavasi** — [@KavasiMihaly](https://github.com/KavasiMihaly) | [OneDayBI](https://www.onedaybi.com)
