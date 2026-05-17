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
- **PowerShell** `>= 5.1` (Windows) or **PowerShell 7+** (cross-platform) — for Dataflow Gen1 discovery and export
  - With `MicrosoftPowerBIMgmt` PowerShell module — install once per user (no admin rights needed):
    ```powershell
    Install-Module -Name MicrosoftPowerBIMgmt -Scope CurrentUser
    ```
    Verify with `Get-Module -ListAvailable -Name MicrosoftPowerBIMgmt`. The generated PowerShell scripts will error out with this install command if the module is missing.
- **Microsoft Fabric CLI** — `pip install ms-fabric-cli` (the plugin's pre-flight check verifies this)
- **Azure CLI** — `az login` for interactive auth, OR a service principal with workspace access
- **Power BI workspace access** — Contributor or higher on the source workspace

---

## Corporate environment setup (TLS interception)

**Run this once if you're on a corporate / managed-AV Windows machine.** Many environments include a TLS-intercepting middlebox or HTTPS-scanning antivirus — Norton, Zscaler, Palo Alto, Sophos, NetSkope, BitDefender, ESET, McAfee, Cisco Umbrella, etc. These re-sign every HTTPS connection with their own root CA. Windows trusts that root because the tool installs it into the Windows certificate store, but **Python-based CLIs do not** — they use the bundled `certifi` cert list, which knows nothing about the corporate root. This breaks:

- `git clone` of the marketplace (manifests as `SSL peer certificate or SSH remote key was not OK`)
- `az login` (`SSL: CERTIFICATE_VERIFY_FAILED` or similar)
- `ms-fabric-cli` / `fab` (same)
- `pip install ms-fabric-cli` against PyPI in some configurations

**Symptoms it's happening:**
- HTTPS works in your browser but fails in CLIs
- The cert chain seen by tools shows an issuer other than DigiCert / Microsoft / Sectigo / GlobalSign — typically your AV or proxy product's name

**The git-only fix** (PowerShell, one-time, no admin):

```powershell
git config --global http.sslBackend schannel
```

This makes git use the Windows TLS stack — which trusts whatever Windows trusts. Solves only git.

**The full fix for every Python-based tool** (PowerShell, one-time, no admin):

```powershell
powershell -File examples\Setup-CorpCertBundle.ps1
```

This script (bundled with the plugin in `examples/`):
1. Exports every root CA from your Windows cert store (including the corporate interceptor's root).
2. Appends them to a copy of Python's certifi bundle.
3. Sets `REQUESTS_CA_BUNDLE` (and `CURL_CA_BUNDLE`) at User scope, permanently.
4. Probes `https://api.fabric.microsoft.com/` to confirm Python now trusts the chain.

After it completes, **close and reopen your terminal** (and Claude Code, if running) so the env var is picked up. `az login` and `fab` calls will then work without any further configuration.

> **Heads-up:** the plugin's pre-flight check (`fabric-preflight-check` skill, runs at orchestrator Pre-Stage in non-sample mode) probes for this issue and surfaces a warning if Python TLS to Microsoft endpoints is broken — so you'll typically be told to run this script before reaching the stages where it matters (Stage 10 onward).

For the root-cause explanation and a full list of which tools are affected, see [`_Documentation/plugin_learnings.md`](_Documentation/plugin_learnings.md) finding N12.

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
| 2 | `fabric-project-initializer` | Project scaffolding + copy plugin reference materials into `6 - Agentic Resources/reference/` (skip if incremental mode) |
| 3 | `dataflow-gen1-extractor` | **(Interactive)** PowerShell export → .pq files |
| 4 | `m-query-analyst` | Inventory + dependency map |
| 5 | `m-query-analyst` | Risk catalog (12 patterns + unknowns) |
| 6 | `migration-analyst` | **(Interactive)** Refactor + strategy decisions |
| 7 | Orchestrator | **(AskUserQuestion)** User approves medallion mapping |
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
| `git clone` of marketplace fails with `SSL peer certificate ... not OK` | Corporate TLS interception. Run `git config --global http.sslBackend schannel` to make git use the Windows cert store. See "Corporate environment setup" above. |
| `az login` fails with `SSL: CERTIFICATE_VERIFY_FAILED` (or similar) | Same root cause but Python-based. Run `powershell -File examples\Setup-CorpCertBundle.ps1` to augment Python's certifi bundle with the Windows trust store. See "Corporate environment setup" above. |
| `fab` CLI not found | `pip install ms-fabric-cli` (the pre-flight check tells you this) |
| `fab` CLI installed but fails with cert errors at Stages 10–12 | Same root cause as `az login` failing — run `Setup-CorpCertBundle.ps1`. |
| `Connect-PowerBIServiceAccount` prints "browser will open" but hangs (no browser) | You're on PowerShell 7 (`pwsh`). Re-run the script with Windows PowerShell 5.1: `powershell -File "..."` instead of `pwsh -File "..."`. PS 5.1 uses an in-process WebBrowser COM auth dialog that doesn't depend on external browser launching. |
| Auth fails | Run `az login` interactively (after Setup-CorpCertBundle if applicable), or set `azure_*` userConfig for SP auth |
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

## Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Pre-1.0 versions are pre-stable — minor bumps may include behavioral changes.

### [0.3.1] — 2026-05-17

Patch follow-up to 0.3.0. Fixes a reference-copy bug that made the N14 fix ineffective on fresh builds. Full root-cause analysis in [`_Documentation/plugin_learnings.md`](_Documentation/plugin_learnings.md) finding N16.

#### Fixed
- **N16 — `fabric-project-initializer` copied only stub reference files on fresh builds.** The scaffolder resolved the bundled reference folder as `<root>/Agents/reference/fabric` whenever `CLAUDE_PLUGIN_ROOT` was not exported into the script's environment. That path does not exist (the real materials ship at `<root>/reference/`), so the "graceful" branch wrote two placeholder files and skipped `m-conversion-risk-catalog.md` — making the orchestrator's Stage 2 reference check (introduced by the N14 fix) fail out of the box. Replaced the env-var-dependent `if/else` with a resolver that searches `$CLAUDE_PLUGIN_ROOT/reference` and every script ancestor's `reference/`, selecting the first directory that contains the catalog sentinel so a partial set is never chosen. The not-found branch is now a loud, actionable error instead of misleading stubs.

### [0.3.0] — 2026-05-15 (later)

Patch follow-up to 0.2.0. Released to address three bugs that 0.2.0 produced when run live against the user's corporate-network Windows machine. Full root-cause analysis in [`_Documentation/plugin_learnings.md`](_Documentation/plugin_learnings.md) findings N14–N15.

#### Changed
- **Pipeline stage order — scaffolding moved from Stage 7 to Stage 2.** Previously the project initializer ran AFTER export/inventory/risk-scan, which meant Stages 3–6 wrote into folders that didn't formally exist yet. `cp` auto-created parent directories, and the orchestrator's Stage 2 export wrote to `1 - Source Dataflows/` while the initializer's `1 - Documentation/` collided at the same prefix. Reordered so scaffolding runs immediately after config Q&A. Old Stages 2–6 are now Stages 3–7; Stages 8–13 unchanged. Finding N14 secondary.
- **Subagent prompts now read references from the project, not the plugin cache.** Stages 5 (risk scan) and 8/9 (builders) reference `6 - Agentic Resources/reference/m-conversion-risk-catalog.md` (project-local) instead of `${CLAUDE_PLUGIN_ROOT}/reference/m-conversion-risk-catalog.md` (plugin cache). Background subagents have restricted filesystem permissions and cannot read paths outside the working directory. The Stage 2 scaffolder copies all five plugin reference files into the project so every later subagent has access. Finding N14.
- **Stage 6 (Refactor Decisions) restructured into three parent-owned sub-steps (6a/6b/6c).** `AskUserQuestion` is not available in any subagent, foreground or background, per the [Claude Agent SDK Limitations docs](https://code.claude.com/docs/en/agent-sdk/user-input.md). 0.2.0's "spawn foreground" approach was based on a wrong premise (N9 was partially wrong; superseded by N15). The orchestrator now (6a) spawns `migration-analyst` in `Mode: analyze` to return a JSON envelope of applicable questions, (6b) calls `AskUserQuestion` itself with that envelope, then (6c) spawns the analyst in `Mode: write` to consume the answers and write Sections 1+5 of migration-design.md. Both analyst spawns are background; neither needs `AskUserQuestion`. Finding N15.

#### Fixed
- **Duplicate `1 -` folder prefix.** Renamed `1 - Source Dataflows/` to `2 - Source Files/dataflow-json/`. Consolidates source artifacts (raw JSON, parsed `.pq` files, inventory CSV) under one numbered folder and eliminates the prefix collision with `1 - Documentation/`.
- **N14 risk-scan permissions block.** Risk-scan subagent could not read the M-conversion risk catalog from the plugin cache; now reads from the project-local copy made during Stage 2 scaffolding.
- **N15 Refactor Q&A silent default-fallback.** Before the Stage 6 refactor, the migration-analyst's `AskUserQuestion` calls silently no-op'd and the analyst wrote unconfirmed defaults to Sections 1+5. Refactor decisions now go through the orchestrator's user channel; the user's actual choices land in the design doc.

#### Removed
- **`AskUserQuestion` from migration-analyst's `tools:` frontmatter.** It was never functional there (subagents cannot use it) and its presence was misleading. The analyst is now a two-mode non-interactive specialist.

### [0.2.0] — 2026-05-15 (released)

First version dogfooded end-to-end on a real corporate-network Windows machine. The changes below were either discovered the hard way during a prior dry-run or built proactively to keep future runs from hitting the same wall. Full root-cause analysis for each "silent failure" pattern is in [`_Documentation/plugin_learnings.md`](_Documentation/plugin_learnings.md) findings N8–N13.

This version shipped to the marketplace and produced two live-discovered bugs that 0.3.0 addresses (see N14 above): a duplicate `1 -` folder prefix from out-of-order scaffolding, and a permissions block when background subagents tried to read reference files from the plugin cache. Plus a third issue surfaced during the same run that 0.3.0 documents but does not yet fix (N15: `AskUserQuestion` doesn't work in subagents at all).

#### Added
- **Stage 1a tenant-wide discovery** — orchestrator now offers a `Discover-AllDataflows.ps1` generation step when the user has no `source_workspace_id`. Lists every workspace × every Gen 1 dataflow accessible to the signed-in user (or every workspace in the tenant for admins via `-Scope Organization`). Output CSV → user picks → orchestrator proceeds to Stage 2.
- **`generate_discovery_script.py`** in the `dataflow-gen1-extractor` skill — companion to the existing `generate_export_script.py`.
- **TLS-interception detection** in the `fabric-preflight-check` skill — probes `https://api.fabric.microsoft.com/` via Python's `ssl` module and emits a non-blocking warning if a corporate proxy/AV is re-signing connections with a root the Python `certifi` bundle doesn't trust.
- **`examples/Setup-CorpCertBundle.ps1`** — one-command helper that augments Python's certifi bundle with the corporate root CAs already trusted by Windows, then sets `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` at user scope. Unblocks `az` CLI, `fab` CLI, and any `requests`-based tool under Norton / Zscaler / Palo Alto / similar.
- **"Corporate environment setup" section** in README, plus expanded troubleshooting table with the specific symptom strings and fix commands.
- **Trust-but-verify step** in orchestrator Stage 8/9 — `ls` confirms each builder's claimed `notebook_path` actually exists on disk before the conformance gate accepts the envelope. Catches silent worktree-style file losses going forward.

#### Changed
- **Orchestrator Stage 5 (refactor Q&A) now spawns `migration-analyst` with explicit `run_in_background: false`** — was relying on a code-style comment that the orchestrating model pattern-matched away, dropping the analyst into background mode where `AskUserQuestion` silently no-ops. Stage 5's design doc is now also verified post-spawn (halt if Section 5 still contains defaults). Finding N9.
- **Orchestrator Stage 6 (design approval) swapped from native plan mode to `AskUserQuestion`** — the orchestrator's `tools:` list didn't include `EnterPlanMode`, so "Enter plan mode" was a silent no-op and the pipeline barreled past the approval gate. Now uses `AskUserQuestion` with `Approve / Revise / Abort` options. Finding N10.
- **Bronze/silver builders no longer use `isolation: worktree`** — the worktree hooks ran `git worktree remove --force` after the agent finished, wiping every `.ipynb` the builder had just written. Builders now write directly to `3 - Notebooks/{bronze,silver}/`; each handles a unique query so no collisions. Finding N8.
- **Discovery + export PowerShell scripts now generated as UTF-8 with BOM** — without a BOM, PS 5.1 falls back to Windows-1252 and misinterprets UTF-8 multi-byte characters (e.g. em-dashes) as multiple chars including a spurious right-double-quote that prematurely closes string literals, cascading into "missing terminator" parse errors. Templates also ASCII-ified for defense in depth. Finding N13.
- **Both PowerShell scripts now strongly recommend Windows PowerShell 5.1 (`powershell -File ...`), not pwsh 7 (`pwsh -File ...`)** — PS 5.1's WebBrowser COM auth uses the Windows cert store (trusts corporate-proxy roots that Python doesn't), and an in-process dialog (doesn't depend on `Process.Start("https://...")` succeeding, which silently hangs in pwsh -File / VS Code terminal / remote sessions). Scripts now print a clear warning if they detect they're running under pwsh 7. Findings N12 + the auth-flow research.
- **Orchestrator Pre-Stage now skips entirely in `--sample` mode** — sample dry-run runs against bundled JSON, generates notebooks locally, and never calls Fabric/Azure, so the preflight (which checks `fab` CLI + Azure auth) is irrelevant. Was previously halting `--sample --dry-run` runs if the user didn't have `fab` installed.
- **Pre-flight envelope now includes a `warnings` array** alongside `checks`/`status`/`remediation`. Orchestrator Pre-Stage surfaces warnings with explicit "this won't block but you should know" framing, special-cases the `tls_interception` warning with the exact fix command.
- **README + quickstart + pipeline-workflow now document `claude --agent ...` from a fresh shell as the only supported launch path** — see N11 below.

#### Removed
- **`/migrate-dataflows` slash command** and the entire `commands/` directory — slash commands run inside an existing Claude session, which would have spawned the orchestrator as a subagent. Claude Code's hierarchy rules prevent a subagent from spawning further subagents, so the orchestrator's own `Task(...)` calls to its 5 specialists silently no-op'd, stalling the pipeline. Orchestrator now must be launched as the main session: `claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "..."` from a fresh shell. Finding N11.
- **`hooks/create-worktree.py` and `hooks/remove-worktree.py`** — orphaned after dropping `isolation: worktree`. The `WorktreeCreate` / `WorktreeRemove` registrations in `plugin.json` removed too. Hook count: 5 → 3.
- **`4 - Semantic Layer/`, `5 - Report Building/`, `7 - Data Exports/`** folders no longer pre-created by `fabric-project-initializer`. The first two were never populated by any plugin stage; the third is lazy-created by the lakehouse-reader skill on first live use. Scaffolded project now contains only the 5 folders the pipeline actually fills.

#### Fixed
- Aligned `homepage` and `repository` URLs in `plugin.json` with the actual GitHub repo name (`Dataflow-to-Notebook-Plugin`); marketplace.json entry corrected to match.

### [0.1.0] — 2026-05-02

Initial release. Structurally complete (six pre-shipment audit gates pass) but untested against a real workspace. See [`_Documentation/plugin_learnings.md`](_Documentation/plugin_learnings.md) findings F1–F9 (inherited from the companion dbt-pipeline-toolkit plugin) and N1–N7 (Fabric-specific design decisions).

---

## Author

**Mihaly Kavasi** — [@KavasiMihaly](https://github.com/KavasiMihaly) | [OneDayBI](https://www.onedaybi.com)
