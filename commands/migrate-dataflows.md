---
description: Power BI Dataflow Gen1 → Microsoft Fabric medallion notebook migration
argument-hint: [--sample] [--dry-run]
---

# /migrate-dataflows

Run the end-to-end Dataflow Gen1 → Fabric medallion notebook migration.

You should immediately invoke the `fabric-migration-orchestrator` agent for this plugin via the Task tool, passing along any flags from the user's invocation.

## What to do

1. Parse the user's flags from `$ARGUMENTS`. Recognize:
   - `--sample` — use bundled sample dataflows from `${CLAUDE_PLUGIN_ROOT}/examples/sample-dataflows/` (no Power BI access needed)
   - `--dry-run` — generate notebooks but skip deployment + lakehouse runtime checks
   - `--help` — print this help text and stop

2. If `--help` was passed, print the usage block below and stop:

```
/migrate-dataflows                       — full migration with deployment
/migrate-dataflows --dry-run             — generate notebooks, skip deployment
/migrate-dataflows --sample              — use bundled sample dataflows (still deploys)
/migrate-dataflows --sample --dry-run    — bundled samples, no Fabric access needed (recommended for first run)

Configuration is read from plugin userConfig (set via /plugin).
See examples/quickstart.md for a full walkthrough.
```

3. Otherwise, invoke the orchestrator with the user's flags forwarded into the prompt:

```
Task(
  subagent_type: "fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator",
  prompt: "Migrate Power BI Dataflow Gen1 dataflows to Fabric medallion notebooks. Flags: <forward $ARGUMENTS verbatim>. Working directory: <print cwd>.",
  // foreground — orchestrator needs main-thread context to spawn its own subagents
)
```

4. Do NOT spawn the orchestrator in background mode. The orchestrator must run as the main thread to delegate via the `Agent` tool — a subagent cannot spawn other subagents per Claude Code's hierarchy rules.

## User-provided arguments

`$ARGUMENTS`
