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
3. **Stage 6** — approval gate (originally plan mode; now `AskUserQuestion` — see N10)

vs the dbt plugin's two touchpoints. The extra Stage 1 exists because Fabric needs config that isn't available at install time (workspace IDs are dynamic) — but it's optional when userConfig is pre-set.

---

## Discovered during first dry-run testing (2026-05-14)

These four findings emerged from running the plugin end-to-end against the bundled `--sample --dry-run` for the first time. They're a class of "silent-failure" bugs — agents reported `status: success`, but the runtime didn't actually deliver what was promised. Each one is worth carrying forward to every future plugin build.

### N8 — Worktree isolation requires a commit-and-merge-back step; without it, agent output is silently destroyed

**Symptom:** All 4 bronze builders reported `status: 'success'` with non-empty `notebook_path` in their envelopes. Conformance gate passed. Then no `.ipynb` files existed in `3 - Notebooks/bronze/`. Trust-but-verify caught it.

**Root cause:** Three layered enabling conditions, all originally inherited from the dbt plugin:

1. `agents/fabric-bronze-builder/agent.md` had `isolation: worktree` in its frontmatter, which forces every spawn into a worktree regardless of what the caller passes.
2. `agents/fabric-silver-builder/agent.md` had the same.
3. `hooks/remove-worktree.py` ran `git worktree remove --force` when the agent finished, wiping the entire worktree filesystem — including the freshly-written `.ipynb` files.

The builder's envelope was honest — it really did write the file. The hook deleted it milliseconds later, before the orchestrator could see it. The dbt plugin works because dbt models are tracked in git and the worktree commits them; the Fabric builders write untracked `.ipynb` files that vanish with the worktree.

**Fix (the simple one applied here):** dropped worktree isolation entirely. Each builder writes to a unique `nb_{layer}_{query}.ipynb` filename, so there was never any actual file-collision risk to justify isolation. The builders now write directly to the main repo's `3 - Notebooks/{bronze,silver}/`. Removed `isolation: worktree` from both builder frontmatters, removed `WorktreeCreate` / `WorktreeRemove` hook registrations from `plugin.json`, deleted `hooks/create-worktree.py` and `hooks/remove-worktree.py`.

**Reusable rule for future plugin builds:** Only adopt `isolation: worktree` if (a) the agent writes files that are already git-tracked AND (b) the WorktreeRemove hook explicitly commits and merges back to the main worktree before the `git worktree remove`. The default dbt-plugin hooks do NOT do this — they assume the agent committed the work itself, which is true for dbt's models-as-source-controlled-text pattern but false for any agent that writes new artifacts like notebooks, generated docs, or build outputs. If your agents create new files, either (a) add a merge-back step to the WorktreeRemove hook before the `git worktree remove --force`, or (b) skip worktree isolation entirely and rely on unique per-agent filenames to avoid collisions.

**Detection mechanism:** the orchestrator's Stage 8/9 now does a trust-but-verify pass — for each builder envelope claiming `status: 'success'`, it `ls`'s the claimed `notebook_path` to confirm the file actually exists on disk. Missing file → halt and surface as a deviation. This belongs in every orchestrator that fans out to background builders; envelopes alone are not enough.

### N9 — Interactive subagents MUST be spawned foreground explicitly; comments are not parameters

**Symptom:** Stage 5 silently produced default refactor decisions in `migration-design.md` — the user was never asked anything. The `migration-analyst` ran, wrote its sections, and returned. No questions appeared.

**Root cause:** The orchestrator's Stage 5 Task spec had `// foreground — needs AskUserQuestion access` as a code-style comment instead of an explicit parameter. Stages 3 and 4 (mechanical analysis) explicitly used `run_in_background: true`. The orchestrating model pattern-matched that syntax onto Stage 5 and inferred away the comment, sending the analyst to the background. Background subagents have no user channel, so `AskUserQuestion` silently no-ops and the analyst falls back to defaults.

**Fix:** Replaced the comment with explicit `run_in_background: false`. Added an emphatic preamble explaining why Stage 5 differs from Stages 3/4. Added a post-spawn verification: read the design doc Section 5 after the analyst returns; if it's blank or default-only, halt rather than silently proceeding.

**Reusable rule for future plugin builds:** Any subagent that calls `AskUserQuestion` (or any other user-facing tool) MUST be spawned with explicit `run_in_background: false`. Do not rely on defaults or comments. After the foreground subagent returns, verify in your orchestrator text that the user-input artifact actually contains user input — not defaults — before proceeding. If the artifact is empty or default-only, halt with an error; do not let the pipeline drift past unattended.

### N10 — Plan-mode approval requires the `EnterPlanMode` tool; `AskUserQuestion` is a simpler substitute

**Symptom:** Stage 6 was supposed to surface a plan-mode review for user approval. It silently no-op'd — the orchestrator just printed a summary and continued to Stage 7. No approval gate was ever shown.

**Root cause:** The orchestrator's `tools:` frontmatter list did not include `EnterPlanMode` or `ExitPlanMode`. The Stage 6 stage instructions said *"Enter native plan mode"* but the agent literally couldn't — the tool wasn't granted. With no tool error visible (just a no-op), the model carried on with the surrounding instructions.

**Fix:** Replaced "Enter native plan mode" with an `AskUserQuestion` flow. Print the migration outcome as a text block first (full context), then issue an `AskUserQuestion` with three options: `Approve and proceed` / `Revise refactor decisions` (loops back to Stage 5) / `Abort` (writes a Section 11 reason, stops cleanly). `AskUserQuestion` was already in the orchestrator's toolset.

**Reusable rule for future plugin builds:** If you want a plan-mode approval gate in an agent, either (a) explicitly add `EnterPlanMode` and `ExitPlanMode` to its `tools:` frontmatter and verify they work in your Claude Code build, or (b) use `AskUserQuestion` with explicit `Approve / Revise / Abort` options. Option (b) is more portable across Claude Code versions and doesn't depend on a tool that might or might not be available. If you choose (a), verify with a fresh-install test that the plan-mode actually fires — silent no-op is the default failure mode here.

### N11 — Slash commands cannot host an orchestrator that delegates to multiple subagents

**Symptom:** This was discovered earlier in the same session but is summarized here for completeness.

**Root cause:** Slash commands run inside an existing Claude session. If a slash command spawns the orchestrator via `Task(...)`, the orchestrator becomes a subagent. Claude Code's hierarchy rules prevent a subagent from spawning further subagents — so the orchestrator's own `Task(...)` calls to its specialists silently no-op, stalling the pipeline.

**Fix:** Deleted the `/migrate-dataflows` slash command entirely. The orchestrator is now launched only as the main Claude session via `claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "..."` from a fresh shell.

**Reusable rule for future plugin builds:** Slash commands cannot host any agent that needs to delegate to multiple subagents. If your plugin has such an agent, document the `claude --agent ...` launch as the canonical entry point and either omit the slash command entirely or have it print a "you must launch from a fresh shell" message rather than silently spawning a broken pipeline.

### N12 — Corporate TLS interception breaks every Python-based CLI, not just git

**Symptom:** During first live-run testing on a machine with Norton Antivirus's "Web/Mail Shield" HTTPS scanning, every Python-backed CLI tool hits SSL handshake failures against `*.microsoft.com`, `api.powerbi.com`, `*.fabric.microsoft.com`:

- `git` — *"SSL peer certificate or SSH remote key was not OK"* (fixed earlier with `git config --global http.sslBackend schannel`)
- `az` CLI — `az login`, `az login --use-device-code`, `az account get-access-token` all fail
- `ms-fabric-cli` (`fab`) — same Python/requests stack, same failure
- Anything else importing `requests` / using `certifi`

**Root cause:** The corporate TLS interceptor (Norton in this case, but Zscaler / Palo Alto / Sophos / NetSkope all behave identically) re-signs HTTPS connections with its own root CA. Windows trusts that root because the interceptor installs it into the Windows certificate store. But every Python tool uses its own bundled `certifi` cert list which knows nothing about the corporate root, so the handshake fails.

**Reusable rules for future plugin builds:**

1. **Prefer Windows-native auth paths for any user-facing prerequisite check.** PowerShell 5.1 + `Connect-*` cmdlets (WebBrowser COM, Windows cert store), ODBC drivers (Windows TLS stack), .NET HttpClient — these "just work" in TLS-intercepted environments because they trust whatever Windows trusts. Reserve Python-based CLIs for environments where you control the trust store.

2. **Do not assume `az login` works.** It's listed in countless Microsoft tutorials as the universal auth on-ramp, but in corporate-network environments it's broken by default. If your plugin requires `az` (the fabric plugin does — for Stages 10–12 fab CLI calls), document the `REQUESTS_CA_BUNDLE` workaround prominently and surface it BEFORE the user hits the failure. Same for `pip install` against PyPI behind a proxy.

3. **The `REQUESTS_CA_BUNDLE` fix:** extract the corporate root CA from the Windows store (`certmgr.msc` → Trusted Root Certification Authorities → export Base-64 .CER), append to a copy of `certifi`'s `cacert.pem`, set `REQUESTS_CA_BUNDLE` env var to the augmented file. One-time per user; survives reboots if set with `setx`.

4. **When a PowerShell script needs an external auth flow** (Power BI, Graph, etc.), **default to Windows PowerShell 5.1 (`powershell.exe -File`)**, not pwsh 7 (`pwsh.exe -File`). PS 5.1's in-process WebBrowser COM auth dialog works in environments where pwsh 7's MSAL-based external-browser launch silently hangs. The fabric plugin's `Discover-AllDataflows.ps1` and `Export-AllDataflows.ps1` are both now explicitly documented as "use PS 5.1, not pwsh 7" for this reason.

**Discovered:** 2026-05-14 during live-test run #1 against the user's corporate-network Windows machine. Reproduced and isolated as a TLS-interception problem (not a tool bug, not an auth bug) by checking the cert chain — issuer was `Norton Web/Mail Shield Root`, not DigiCert.

---

## Open questions for first fresh-install run

These will be filled in after Phase 10 testing:

- **Does the SessionStart hook fire reliably?** The dbt plugin's `userConfig` prompt didn't fire in some installs. SessionStart is the mitigation — but does it actually run on every session start in the plugin context?
- **Does `validate-fabric-structure.py` block correctly on `.py` writes to `3 - Notebooks/`?** Need to verify the hook receives the file path correctly and emits a `decision: block`.
- **Does `migration-analyst`'s `AskUserQuestion` work in the plan-mode pre-flight stage?** The agent runs foreground, but there may be quirks with combining `AskUserQuestion` and the orchestrator's plan-mode entry.
- **Does the `fabric-notebook-deployer` skill work end-to-end against a real workspace?** The Fabric REST API call shape (`POST /v1/workspaces/<id>/notebooks` with base64 payload) is documented but unverified in this context.
- **Does the orchestrator successfully pass `mode: "acceptEdits"` at every Task spawn?** Pre-shipment audit doesn't directly check this — needs runtime verification.
- ~~**Do worktree hooks work on Windows for parallel bronze builds?**~~ ANSWERED 2026-05-14 — no. The default dbt-style hooks `git worktree remove --force` the agent's filesystem before any output is merged back, destroying every uncommitted file the agent just wrote. Worktree isolation is unsafe for any agent that writes new untracked files. See N8 for the resolution.

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

~50 files. 6 agents, 8 skills, 3 hooks, 5 reference docs, 2 sample dataflows, 1 quickstart, 1 README, 1 plugin manifest, 2 test scripts. (No slash command — the orchestrator launches as the main agent via `claude --agent ...`, not via a slash command, to satisfy Claude Code's subagent hierarchy rules. Hook count dropped from 5 to 3 after the 2026-05-14 worktree removal — see N8.)

---

## Inventory snapshot (2026-05-02)

| Category | Count | Notes |
|---|---|---|
| Agents | 6 | 4 net-new, 2 vendored |
| Skills | 8 | 6 vendored, 2 net-new |
| Hooks | 3 | 2 net-new (Bash auto-approval, structure validator), 1 generic (session config check); 2 worktree hooks removed 2026-05-14 — see N8 |
| Reference docs | 5 | 4 copied, 1 net-new (risk catalog) |
| Sample dataflows | 2 | net-new synthetic JSONs |
| Test scripts | 2 | net-new pre-shipment audit + notebook validator |
| Lines of net-new content | ~3500 | rough estimate |
| Lines of vendored content | ~5000 | rough estimate |

---

## Conversion backlog seed

The `_Documentation/conversion-backlog.md` file starts empty. It auto-populates during the first real run when `m-query-analyst` Pass 2 detects M patterns not in the risk catalog.
