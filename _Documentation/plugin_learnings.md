# Plugin Learnings — fabric-dataflow-migration-toolkit

Working notes and discoveries from building this plugin. Companion to the dbt-pipeline-toolkit's [plugin_learnings.md](https://github.com/KavasiMihaly/DBT-Pipeline-Plugin/blob/main/_Documentation/plugin_learnings.md) — that doc's 10 findings shaped every architectural decision in this plugin, so applicable findings are summarized here as adopted patterns rather than re-discovered ones.

This doc is intended to grow during fresh-install testing. The initial build is structurally complete (all pre-shipment audit gates pass) but no end-to-end run has been performed yet.

---

## Inherited findings (applied at build time)

These dbt-plugin findings shaped the initial v0.1 implementation. Each was applied proactively rather than discovered the hard way.

### F1 — 3-part agent namespace (subdirectory layout)

The 6 plugin agents all live under `agents/<name>/agent.md` (subdirectory layout). On install, they register as 3-part names:

```
fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator
fabric-dataflow-migration-toolkit:m-query-analyst:m-query-analyst
... etc
```

Every `subagent_type:` reference in the orchestrator and every `Agent(...)` allowlist entry uses the full 3-part form. The pre-shipment audit (`tests/preshipment_audit.py` `gate_namespace`) catches bare-name regressions automatically.

### F2 — `permissionMode` stripped from plugin agents

`fabric-bronze-builder` originally had `permissionMode: acceptEdits` in its frontmatter (from the standalone version). On vendor-import, that line was removed and the orchestrator now passes `mode: "acceptEdits"` at every Task spawn site. `fabric-silver-builder` was already missing the field — added an explicit note in its agent body explaining the call-site pattern.

### F3 + F9 — Background subagents need plugin-level Bash auto-approval

The plugin ships `hooks/approve-plugin-bash.py` with a Fabric-specific allowlist:
- Plugin-internal Python scripts (`${CLAUDE_PLUGIN_ROOT}/skills/*/scripts/*.py`)
- `fab` CLI subcommands (`auth`, `cd`, `ls`, `get`, `import`, `export`, `api`, `job`, `workspace`, `item`)
- `az` CLI account commands (preflight)
- `pwsh -File ...Export-AllDataflows.ps1` (Stage 2 export)
- Filesystem discovery (`ls`, `find -name "*.pq"`, `find -name "*.ipynb"`)
- `grep` for risk-pattern scanning (m-query-analyst Pass 2)
- Bundled-sample copy (`cp -r ${CLAUDE_PLUGIN_ROOT}/examples/sample-dataflows/. "1 - Source Dataflows/"`)

### F5 — userConfig env var remap

Two scripts read FABRIC_* env vars and need the helper:
- `skills/fabric-lakehouse-reader/scripts/query_fabric_lakehouse.py`
- `skills/fabric-notebook-deployer/scripts/deploy_notebooks.py`
- `skills/fabric-preflight-check/scripts/preflight.py`

Each contains a `_load_plugin_userconfig_env()` helper that maps `CLAUDE_PLUGIN_OPTION_azure_*` to `FABRIC_TENANT_ID` / `FABRIC_CLIENT_ID` / `FABRIC_CLIENT_SECRET` BEFORE argparse evaluates defaults. Mirrors the dbt plugin's approach.

The data-profiler is shared with the dbt plugin and uses its own `SQL_*` mapping helper.

### F7 — `${CLAUDE_PLUGIN_ROOT}` not `$HOME/.claude/skills/`

107 path occurrences across 4 vendored SKILL.md files were normalized in a single mechanical pass during Phase 2:

```
C:\Users\kavas\.claude\skills\<name>\scripts\<file>.py
  →
${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/<file>.py
```

Plus backslash-to-forward-slash normalization inside the script segment. The pre-shipment audit `gate_paths` catches regressions automatically.

### F8 — Agent `skills:` frontmatter uses 2-part namespace

Every agent's `skills:` frontmatter field uses `fabric-dataflow-migration-toolkit:<skill>` 2-part names (not the 3-part form used for agent references). Pre-shipment audit `gate_skills_frontmatter` validates this.

### F9 (continued) — Atomic Bash everywhere

Every agent.md and SKILL.md follows the atomic-Bash rule: no `&&`, `||`, `;`, `|`, `$(`, backticks, subshells, heredocs in any Bash code block. The orchestrator's stage prompts and the pre-shipment audit `gate_atomic_bash` enforce this.

One initial violation was caught at audit time: `fabric-cli-runner/SKILL.md` had a `for` loop with `$(basename ...)` showing bulk import. Replaced with a pointer to the new `fabric-notebook-deployer` skill which provides the same functionality as a single atomic call.

---

## New findings — Fabric-specific

### N1 — `.ipynb`, not `.py`

Microsoft Fabric's notebook deploy API treats `.py` files as a single mega-cell. Real notebooks must be `.ipynb` (Jupyter JSON) with proper `cells[]` arrays.

The `validate-fabric-structure.py` PreToolUse hook blocks any Write/Edit of `.py` files in `3 - Notebooks/` with a clear remediation message. The `fabric-bronze-builder` and `fabric-silver-builder` agent bodies both explicitly require `.ipynb` output.

### N2 — Silver `read_bronze()`-only contract is enforceable at the hook layer

The plugin's Stage 9 silver builder is strictly contracted: silver notebooks may only read via `read_bronze()`. External reads (`spark.read.csv`, `pd.read_csv`, `abfss://`, `Files/`) are bronze's job.

This contract is enforced 3 ways:
1. **Build time** — `fabric-silver-builder/agent.md` body has the rule prominently
2. **Static** — `validate-fabric-structure.py` hook blocks Writes that violate it
3. **Validation** — `fabric-pipeline-validator` re-checks at Stage 12 against the registered notebooks

This belt-and-suspenders approach matches the dbt plugin's "rule in 6 places" pattern — multiple audiences read different files, each needs the rule where they look.

### N3 — Migration plugins don't need a business-analyst

Initial design had a `business-analyst` agent. Removed in favor of `migration-analyst` because the M code already encodes business intent — there's no discovery to do. `migration-analyst` asks technical refactor questions (Combine Files strategy, Excel handling, naming) instead.

This matches Microsoft's official Gen1→Gen2 migration guidance, which is purely mechanical (Export template / Copy-paste / Save As — no requirements gathering).

### N4 — Dynamic question selection in migration-analyst

Hardcoded "always ask 5 questions" patterns are wasteful when most workspaces use a subset of patterns. `migration-analyst` reads `m-analysis-inventory.json` first and asks ONLY questions that apply:
- Excel question only if Excel sources detected
- Combine Files question only if helper queries found
- AzureStorage question only if blob URIs found

Capped at 4 questions max in a single `AskUserQuestion` call. Users with all-CSV workspaces get the minimum (1-2 questions). Users with mixed-source workspaces get the relevant decisions.

### N5 — Risk-isolation cells, not silent TODOs

Per user direction, risky M conversions emit best-effort PySpark in a clearly-marked isolation cell:

```python
# === HIGH RISK / HUMAN REVIEW REQUIRED ===
# Pattern: Excel.Workbook (RISK-03)
# ... best-effort code ...
# === END HIGH RISK ===
```

vs. silent `# TODO: convert this manually`. The user can grep for `HIGH RISK` to find every spot needing review. The `fabric-pipeline-validator` agent counts these and reports them as INFO-level findings.

Patterns the converter doesn't yet recognize get auto-added to `_Documentation/conversion-backlog.md` for future plugin releases.

### N6 — `--sample --dry-run` for offline first-run

Bundled `examples/sample-dataflows/Sample Education Data.json` and `Sample Population Data.json` exercise the major risk patterns (CSV, Excel, Combine Files, NestedJoin, conditional column, UnpivotOtherColumns). Combined with `--dry-run` mode, a new user can run the full pipeline with zero Fabric/Power BI access.

This gives users a complete picture of what the plugin produces before they point at production data — best-onboarding pattern from the marketplace research.

### N7 — Three-touchpoint user budget

Migration tools are mostly mechanical, so user touchpoints should be minimal:
1. **Stage 1** — config (workspace ID, lakehouse names) — skipped if userConfig is set
2. **Stage 5** — refactor decisions (dynamic 3-4 questions)
3. **Stage 6** — plan-mode approval

vs the dbt plugin's two touchpoints. The extra Stage 1 exists because Fabric needs config that isn't available at install time (workspace IDs are dynamic) — but it's optional when userConfig is pre-set.

---

## Open questions for first fresh-install run

These will be filled in after Phase 10 testing:

- **Does the SessionStart hook fire reliably?** The dbt plugin's `userConfig` prompt didn't fire in some installs. SessionStart is the mitigation — but does it actually run on every session start in the plugin context?
- **Does `validate-fabric-structure.py` block correctly on `.py` writes to `3 - Notebooks/`?** Need to verify the hook receives the file path correctly and emits a `decision: block`.
- **Does `migration-analyst`'s `AskUserQuestion` work in the plan-mode pre-flight stage?** The agent runs foreground, but there may be quirks with combining `AskUserQuestion` and the orchestrator's plan-mode entry.
- **Does the `fabric-notebook-deployer` skill work end-to-end against a real workspace?** The Fabric REST API call shape (`POST /v1/workspaces/<id>/notebooks` with base64 payload) is documented but unverified in this context.
- **Does the orchestrator successfully pass `mode: "acceptEdits"` at every Task spawn?** Pre-shipment audit doesn't directly check this — needs runtime verification.
- **Do worktree hooks work on Windows for parallel bronze builds?** The dbt plugin uses these without issue, but Windows path handling sometimes surfaces edge cases.

---

## Pre-shipment audit results (initial build)

```
=== Pre-shipment audit: fabric-dataflow-migration-toolkit ===

  [PASS] required_files
  [PASS] plugin_manifest
  [PASS] paths
  [PASS] namespace
  [PASS] skills_frontmatter
  [PASS] atomic_bash

Overall: PASS
```

~50 files. 6 agents, 8 skills, 5 hooks, 5 reference docs, 2 sample dataflows, 1 quickstart, 1 README, 1 plugin manifest, 2 test scripts. (No slash command — the orchestrator launches as the main agent via `claude --agent ...`, not via a slash command, to satisfy Claude Code's subagent hierarchy rules.)

---

## Inventory snapshot (2026-05-02)

| Category | Count | Notes |
|---|---|---|
| Agents | 6 | 4 net-new, 2 vendored |
| Skills | 8 | 6 vendored, 2 net-new |
| Hooks | 5 | 2 mirrored from dbt, 2 net-new, 1 generic |
| Reference docs | 5 | 4 copied, 1 net-new (risk catalog) |
| Sample dataflows | 2 | net-new synthetic JSONs |
| Test scripts | 2 | net-new pre-shipment audit + notebook validator |
| Lines of net-new content | ~3500 | rough estimate |
| Lines of vendored content | ~5000 | rough estimate |

---

## Conversion backlog seed

The `_Documentation/conversion-backlog.md` file starts empty. It auto-populates during the first real run when `m-query-analyst` Pass 2 detects M patterns not in the risk catalog.
