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
- Bundled-sample copy (`cp -r ${CLAUDE_PLUGIN_ROOT}/examples/sample-dataflows/. "2 - Source Files/dataflow-json/"`)

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

### N13 — PowerShell scripts must be UTF-8 with BOM (or pure ASCII) for PS 5.1

**Symptom:** A generated `Discover-AllDataflows.ps1` parsed cleanly under `pwsh 7` (verified via `[System.Management.Automation.Language.Parser]::ParseFile()`) but failed under Windows PowerShell 5.1 (`powershell -File`) with cascading "The string is missing the terminator: \"." errors pointing at correctly-closed strings several lines below where the real problem actually was. Earlier orchestrator diagnosis blamed an unrelated `<GUID>` placeholder inside a single-quoted string; that diagnosis was wrong.

**Root cause:** PS 5.1's file reader, when there is no UTF-8 BOM, falls back to the OS default code page (typically Windows-1252 in en-US installs). A single UTF-8 em-dash character `—` (U+2014, byte sequence `0xE2 0x80 0x94`) becomes three separate Windows-1252 characters when misinterpreted: `â`, `€`, and `”` (U+201D right double quote). When the em-dash sits inside a double-quoted string, the spurious `”` closes the string early, and PS 5.1 then tries to parse the remainder as code — manifesting as "missing terminator" errors many lines later. Same hazard applies to en-dashes, smart quotes, ellipses, arrows, any character outside the 7-bit ASCII range.

`pwsh 7` reads UTF-8 by default and does not have this hazard. The user-facing test environment runs `powershell -File` deliberately (PS 5.1's WebBrowser COM auth is the only auth path that survives corporate TLS interception — see N12), so the bug only fires after the *correct* fix for N12 is applied. This is a particularly cruel ordering: the more carefully a user follows the documented advice, the more likely they are to hit it.

**Fix:** two-layer defense:

1. **Write all generated PowerShell scripts as UTF-8 with BOM** — Python: `open(path, "w", encoding="utf-8-sig")` or `Path.write_text(content, encoding="utf-8-sig")`. The BOM is `0xEF 0xBB 0xBF`; PS 5.1 recognizes it and switches to UTF-8 mode. Existing pre-PS 5 readers also handle it gracefully.
2. **Avoid non-ASCII characters inside PowerShell string literals** anyway, even with the BOM — defense in depth. ASCII hyphens (`-`, `--`), arrows (`->`), and plain quotes (`"`, `'`) read identically under every code page. Reserve UTF-8 multibyte characters for Markdown / Python source where the encoding is unambiguous.
3. **Audit existing PowerShell content** for em-dashes, en-dashes, smart quotes, arrows, ellipses, degree signs, and other common typographic Unicode. Static `.ps1` files in the repo: rewrite as UTF-8 with BOM via a one-shot Python script. Generated `.ps1`: fix the Python templates AND switch the writer to `utf-8-sig`.

**Reusable rule for future plugin builds:** Any tooling that *generates* PowerShell, batch, or other Windows-script files MUST default to UTF-8 with BOM. Any *static* PowerShell content checked into a repo MUST either be UTF-8-with-BOM or strictly 7-bit ASCII. Don't trust that "the orchestrator parsed the script and said it was fine" — ensure your parse-check uses the same PowerShell edition (5.1 vs 7) the user will run, because the parsers diverge silently on encoding handling. The fabric plugin's `generate_discovery_script.py` and `generate_export_script.py` both now use `encoding="utf-8-sig"`; `examples/Setup-CorpCertBundle.ps1` was prepended with a BOM in-place.

**Discovered:** 2026-05-15. Confirmed by parsing the regenerated script with `powershell.exe -Command [Parser]::ParseFile(...)` — clean — and contrasting with the original which produced the observed cascade.

### N14 — Background subagents cannot read plugin-cache paths; copy references into the project at scaffold time

**Symptom:** The risk-scan subagent (`m-query-analyst` Pass 2, spawned in background) hit a permissions block reading `${CLAUDE_PLUGIN_ROOT}/reference/m-conversion-risk-catalog.md`. Without the catalog, the scan can't classify any of the discovered M patterns and the pipeline either halts or produces an empty risks JSON.

**Root cause:** Background subagents run with restricted filesystem permissions and CANNOT read files outside the project's working directory — including paths inside the plugin cache (`~/.claude/plugins/cache/.../reference/...`). The orchestrator referenced these paths in the subagent prompts assuming any agent invoked from the orchestrator inherits its read scope. That assumption is wrong for backgrounded `Task()` calls.

**Secondary finding (uncovered while fixing N14):** the orchestrator's stage ordering was also wrong. Stage 7 was project scaffolding, but Stages 2–6 (export, inventory, risk scan, refactor, approval) all wrote into the project structure that Stage 7 was supposed to create. The folders were being created ad-hoc during earlier stages because `cp` / `mv` auto-creates parent directories, leading to duplicates like the simultaneous `1 - Documentation/` (initializer) and `1 - Source Dataflows/` (Stage 2 export — wrong prefix, conflicting number).

**Fix:** two coordinated changes:

1. **Moved scaffolding earlier.** Stage 7 (Project Scaffolding) is now Stage 2, between config Q&A and export. Old Stages 2–6 became Stages 3–7. Scaffolding now runs BEFORE any other stage writes into the project, so the folder layout is always in place.

2. **Scaffolder copies plugin reference materials into the project.** `fabric-project-initializer` always copies `${CLAUDE_PLUGIN_ROOT}/reference/*` into `6 - Agentic Resources/reference/` at scaffold time (this behavior already existed; the fix was making sure scaffolding runs before any subagent that needs them). The orchestrator's Stage 5 (risk scan) and Stage 8/9 (builder) prompts now point at `6 - Agentic Resources/reference/m-conversion-risk-catalog.md` (project-local) instead of `${CLAUDE_PLUGIN_ROOT}/reference/m-conversion-risk-catalog.md` (plugin cache).

**Reusable rule for future plugin builds:** Any reference file, template, or read-only resource that background subagents need MUST live in the project's working directory by the time the subagent fires — not in the plugin's installation cache. Three patterns work:

- **Copy at scaffold time** (used here). Project initializer copies plugin reference materials into the project once; subagent prompts use project-local paths from then on. Best when references are small and stable.
- **Pass the content inline in the subagent prompt** (alternative). Orchestrator reads the plugin-cache file itself (its permissions are unrestricted), embeds the content into the subagent's prompt string. Best when references are very small and changes shouldn't require a project re-scaffold.
- **Make the subagent foreground** (escape hatch). Foreground subagents have the orchestrator's permission scope and CAN read plugin-cache paths. But this defeats parallel-fan-out designs and ties up the orchestrator's interactive channel. Use only when the other two patterns don't apply.

Also: when stages produce filesystem artifacts that later stages depend on, **the stage ordering must match the dependency order**. Stage 7 producing folders that Stages 2–6 already wrote into is a textbook ordering bug — caught here only by a user noticing the duplicate numbered folder prefix. Linting idea for future plugin audits: each stage prompt declares the paths it writes to and the paths it reads from; the audit checks that no read path appears before its write path in the stage sequence.

**Discovered:** 2026-05-15 during second wave of live-test runs against the user's corporate-network Windows machine, after fixing N12 (TLS interception) and N13 (PS 5.1 encoding) unblocked the discovery flow.

### N15 — `AskUserQuestion` is NOT available in any subagent, regardless of foreground/background

**Symptom:** Stage 5/6 (Refactor Q&A) in the orchestrator spawned `migration-analyst` with `run_in_background: false` and `tools: ..., AskUserQuestion` in the analyst's frontmatter. The analyst nonetheless reported that `AskUserQuestion` was not available, wrote sensible default values to Sections 1+5 of migration-design.md, and asked the orchestrator to confirm them via the parent's user channel. The 0.2.0 N9 fix ("spawn foreground for interactive subagents") was based on a wrong premise.

**Root cause:** Documented explicitly in the [Claude Agent SDK user-input docs](https://code.claude.com/docs/en/agent-sdk/user-input.md) under Limitations:

> **Subagents:** `AskUserQuestion` is not currently available in subagents spawned via the Agent tool.

This is a hard restriction, not foreground/background-dependent. Listing the tool in a subagent's `tools:` frontmatter has no effect — the orchestrator's main session is the only place `AskUserQuestion` works. N9's earlier "spawn foreground for AskUserQuestion access" advice was therefore wrong; the correct rule (supersedes N9 for the interactive-tool case specifically) is: **the parent always owns interactive Q&A; subagents are purely deterministic specialists**.

**Fix (implemented in 0.3.0):** Refactored Stage 6 into a three-sub-step parent-owned pattern:

- **6a — Analyst in `Mode: analyze`** reads inventory + risks, returns JSON envelope `1 - Documentation/refactor-questions.json` listing applicable questions with their options. Pure analysis, no user interaction.
- **6b — Orchestrator** reads the envelope, calls `AskUserQuestion` itself with the questions array, writes the user's chosen labels to `1 - Documentation/refactor-answers.json`.
- **6c — Analyst in `Mode: write`** reads inventory + risks + answers, writes Sections 1+5 of `migration-design.md` deterministically.

Both analyst spawns run in background; neither needs `AskUserQuestion`. The analyst's `tools:` frontmatter no longer claims `AskUserQuestion`.

**Reusable rule for future plugin builds:** any time an orchestrator design sketches "specialist subagent that asks the user something," restructure into a three-sub-step parent-owned pattern:

1. Subagent emits JSON envelope of questions/decisions to be made
2. Parent calls `AskUserQuestion` with the envelope
3. Subagent consumes answers and produces the side-effecting outputs

This is the same shape as the SDK's documented graceful-degradation behavior — when a subagent hits `AskUserQuestion`, it falls back to writing defaults and asking the parent. Codifying this as the FIRST design (rather than the FALLBACK) makes the pipeline deterministic and removes a class of silent-failure bugs.

**Companion N15 corrections to earlier findings:**

- **N9 was partially wrong.** N9 said "spawn interactive subagents in foreground." That advice helps for some interactive tools (permission prompts pass through to the user in foreground), but NOT for `AskUserQuestion` which is hard-restricted from subagents entirely. The complete rule is: AskUserQuestion only lives in the parent; foreground vs background is irrelevant to its availability.
- **N10's plan-mode parallel.** N10 noted plan-mode silently no-ops when `EnterPlanMode` isn't in the orchestrator's tools. The same class as N15: an interactive tool unavailable in a context where the code assumed it would be. Both findings now resolve to the same parent-side pattern — parent owns the interaction, subagent prepares/consumes structured data.

**Discovered:** 2026-05-15 during live-test run. Validated via claude-code-guide agent fetching the SDK Limitations docs directly.

### N16 — The N14 reference-copy fix was ineffective: scaffolder fell back to a non-existent path and shipped stub files

**Symptom:** On a fresh build, the orchestrator's Stage 2 mandatory check on `6 - Agentic Resources/reference/m-conversion-risk-catalog.md` failed every time. The folder contained only two files (`notebook-template.md`, `pyspark-style-guide.md`) — and those were one-line stubs ("See Agents/reference/fabric/ for the full guide"), not the real reference materials.

**Root cause:** `fabric-project-initializer`'s reference resolution was `if CLAUDE_PLUGIN_ROOT: <plugin_root>/reference else: <script>/../../../Agents/reference/fabric`. The `else` path is wrong twice over — there is no `Agents/` directory anywhere in the plugin, and the real reference folder ships at the repo/plugin **root** as `reference/` (5 files). Whenever `CLAUDE_PLUGIN_ROOT` was not exported into the *script subprocess's* environment (it is a plugin-context variable, not reliably inherited by `python ...` invoked from an orchestrator Bash call), the script took the broken `else` branch, `source_reference_path.exists()` returned False, and `create_agentic_resources` silently wrote two placeholder stubs. N14's point 2 explicitly assumed "this behavior already existed" — it did, but it was broken in exactly the no-env-var case, so the N14 fix (point subagents at the project-local copy) pointed them at a folder missing the catalog.

**Fix (implemented in 0.3.1):** Replaced the env-var `if/else` with `resolve_reference_source()`, which builds an ordered candidate list — `$CLAUDE_PLUGIN_ROOT/reference` first (when set), then `<ancestor>/reference` for every ancestor of the resolved script path — and returns the first directory containing the sentinel file `m-conversion-risk-catalog.md` (so a partial/stub folder is never selected), else the first directory that merely exists, else None. Because the script lives at `<root>/skills/fabric-project-initializer/scripts/`, the ancestor walk always finds `<root>/reference` even with no env var, eliminating the dependency entirely. The not-found branch now prints a loud, actionable error and writes a single `MISSING-REFERENCE.md` explaining the remediation, instead of stub files that masquerade as real guides and pass a naive existence check. Verified both with and without `CLAUDE_PLUGIN_ROOT` set: all five files (including the sentinel) land flat in `6 - Agentic Resources/reference/`, no `reference/reference/` nesting.

**Reusable rule for future plugin builds:** Never resolve a bundled resource through a single env var with a hardcoded relative fallback. (1) `CLAUDE_PLUGIN_ROOT` is set in the plugin/agent context but is NOT guaranteed to propagate into subprocesses the orchestrator launches via Bash — treat it as a hint, not a contract. (2) Resolve bundled resources by walking the script's own ancestors (`Path(__file__).resolve().parents`) — that path is always correct regardless of how the script was invoked or installed. (3) Validate the resolved directory by the presence of a known sentinel file, not just `dir.exists()`, so a half-populated or stub folder is rejected rather than silently accepted. (4) A "graceful degradation" branch that writes plausible-looking placeholder content is worse than a loud failure when a downstream stage hard-checks for the real content — degrade loudly, with the remediation in the artifact.

**Discovered:** 2026-05-17 via agent-memory note `project_scaffolder_reference_bug.md` recorded by the orchestrator during a fresh build, then root-caused in the plugin source.

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
