# Pipeline Workflow — Process Map

**Last updated:** 2026-06-08
**Applies to:** `fabric-dataflow-migration-toolkit` plugin v0.x (pre-stable)

This document is the authoritative narrative of the 13-stage migration pipeline. The orchestrator's `agent.md` is the implementation; this is the process map and contract reference for plugin contributors.

## Audience

- **Plugin users** — understand what will happen before approving the plan
- **Plugin contributors** — understand how stages fit together so a change to one doesn't break the contract the next depends on

## Invocation

The orchestrator must run as the **main Claude session**. Launch from a fresh shell, not from inside an existing Claude session:

```bash
# Full migration with deployment
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows from workspace <GUID>"

# Generate notebooks, skip deployment
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows. Flags: --dry-run"

# Bundled samples, no Fabric access
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate sample dataflows. Flags: --sample --dry-run"
```

The orchestrator runs in the user's working directory. All paths are relative to cwd unless absolute. It must be the main thread because it delegates to 5 specialist subagents — and Claude Code's hierarchy rules prevent a subagent from spawning further subagents.

## Notebook engine toggle (`pyspark` | `python`)

A migration emits notebooks for **one** compute engine, chosen **once at the start of the run** via the `notebook_engine` userConfig or the orchestrator's `--engine python|pyspark` flag (the flag wins). **No mixing** — one engine per project. The choice is resolved at **Stage 1**, recorded in Section 0 of `migration-design.md` and in `0 - Architecture Setup/project-config.yml` (`project.engine`), threaded into every builder prompt (Stages 8/9), and surfaced in the Stage 7 approval text (with the single-node caveat for `python`). `pyspark` is the default and the regression baseline.

### Decision matrix

| | `pyspark` (default) | `python` |
|---|---|---|
| Kernel | `synapse_pyspark` (Spark cluster) | `jupyter` (`microsoft.language_group: jupyter_python`) |
| Runtime | Distributed Spark | Single-node (2 vCore / 16 GB) |
| Libraries | PySpark / Spark SQL | polars / duckdb / delta-rs |
| Best for | Larger / distributed workloads | Low-volume (sub-gigabyte) — faster start, lower cost |
| Guidance | [Fabric notebook selection guide](https://learn.microsoft.com/en-us/fabric/data-engineering/fabric-notebook-selection-guide) | same |

The migration holds only M code (never source rows), so there is **no data-driven engine advisory** — the toggle is the user's call. The single-node memory caveat lives in docs + the Stage-7 approval text, **not** as a gate.

### Python engine limitations (bake into the engine choice)

- **Single-node memory** — one ~16 GB container, no distributed fan-out. Comfortable up to ~1 GB of working data; multi-GB transforms (especially large joins) risk OOM. Pick `pyspark` for anything that needs a cluster.
- **No env vars / no Environment item / no library item** — packages not pre-installed must come via inline `%pip install`; config a Spark path would read from an Environment must be inlined or read from `project-config.yml`.
- **Some Delta features unsupported** — Delta I/O via delta-rs + polars is not the full Delta spec. **V-Order / Native Execution Engine (NEE) / Vegas cache are Spark-only (N-A in Python)** — write-time performance optimizations, not correctness; tables stay queryable and can be V-Order-optimized later by a Spark `OPTIMIZE` job or the SQL endpoint's background optimization.

The engine-aware gates (Stage 8/9 hook + Stage 12 validator) enforce the **per-engine** contract — Python silver still must be `read_bronze`-only, Python bronze still `write_deltalake(... append ...)` — and catch cross-engine idiom leakage. The `reference/m-conversion-risk-catalog.md` tags every M risk with a `**Python:**` applicability note (ease / worsen / N-A / unchanged) describing how each mitigation shifts on the single-node engine.

> **Status (2026-06-08):** the Python builders + the M→Python converter emit Python-kernel notebooks; what remains is the **manual, offline-for-now live Fabric round-trip** (deploy + confirm the notebooks register as Python and that `table_path()` writes register the Delta tables). `pyspark` stays the default.

## User interaction budget

Three interactive touchpoints. Everything else autonomous.

1. **Stage 1: Config Q&A** — workspace + lakehouse selections (skipped if userConfig set), plus optional Stage 1a tenant-wide dataflow discovery for users without a workspace ID
2. **Stage 6: Refactor decisions** — dynamic 3-4 questions via `migration-analyst`
3. **Stage 7: Design approval** — `AskUserQuestion`-based Approve / Revise / Abort gate

A fourth conditional touchpoint: **deviation escalation** at Stages 8, 9, or 10 if a builder/deployer can't satisfy its prompt. Only fires on contract breaks — clean runs never hit it.

## The master document

All design decisions, plans, build outputs, and validation results live in **`1 - Documentation/migration-design.md`**. Every stage reads it; specialists return JSON envelopes that the orchestrator merges into specific sections.

### Section ownership

| Section | Owner | When written |
|---|---|---|
| 0. Configuration | orchestrator | Stage 1 |
| 1. Migration Goals | `migration-analyst` direct | Stage 6 |
| 2. Dataflow Inventory | orchestrator from m-query-analyst JSON | Stage 4 |
| 3. Risk Catalog | orchestrator from m-query-analyst JSON | Stage 5 |
| 4. Dependency Map | orchestrator from m-query-analyst JSON | Stage 4 |
| 5. Refactor Decisions | `migration-analyst` direct | Stage 6 |
| 6. Medallion Mapping | orchestrator | Stage 6 |
| 7. Bronze Build Plan | orchestrator drafts; bronze builders fill rows | Stage 6 + 8 |
| 8. Silver Build Plan | orchestrator drafts; silver builders fill rows | Stage 6 + 9 |
| 9. Created Notebooks Registry | orchestrator | After every successful build |
| 10. Validation Results | `fabric-pipeline-validator` direct | Stage 12 |
| 11. Design Decisions Log | orchestrator | Throughout |
| 12. Migration Report | orchestrator | Stage 13 |

## The 13 stages (summary)

| Stage | Owner | Mode | Side effects |
|---|---|---|---|
| Pre | `fabric-preflight-check` | Auto | Fail fast if `fab` / `az login` missing; emit TLS-interception warning if Python can't verify Microsoft endpoints (does not block) |
| 0 | Orchestrator | Auto | Detect fresh build vs incremental |
| 1 | Orchestrator | Interactive | Ask config (workspace, lakehouses); Stage 1a optionally generates tenant-wide discovery script |
| 2 | `fabric-project-initializer` | Auto | Project scaffolding + copy plugin reference materials into `6 - Agentic Resources/reference/` (skip if incremental) |
| 3 | `dataflow-gen1-extractor` | Interactive (PowerShell auth) | Export Gen1 JSON → parse to .pq files |
| 4 | `m-query-analyst` Pass 1 | Background | Inventory, classification, dependency map |
| 5 | `m-query-analyst` Pass 2 | Background | Risk catalog scan; backlog entries for unknowns. Reads catalog from project-local `6 - Agentic Resources/reference/` (copied at Stage 2) |
| 6 | `migration-analyst` | Interactive | Refactor + strategy decisions |
| 7 | Orchestrator | Interactive (AskUserQuestion) | User approves medallion mapping; Approve / Revise / Abort |
| 8 | `fabric-bronze-builder` × N | Background parallel | Bronze .ipynb generation |
| 9 | `fabric-silver-builder` × N | Background canary + parallel | Silver .ipynb (read_bronze() only) |
| 10 | `fabric-notebook-deployer` | Auto (skip in dry-run) | `fab import` per notebook |
| 11 | `fabric-cli-runner` | Auto (skip in dry-run) | `fab job run` bronze, then silver |
| 12 | `fabric-pipeline-validator` | Background | Static + runtime validation, Section 10 |
| 13 | Orchestrator | Auto | Migration Report.md |

See `agents/fabric-migration-orchestrator/agent.md` for the full implementation including Bash commands for each stage.

## Strict conformance gates (Stages 8 + 9)

After parallel builders complete, the orchestrator scans every JSON envelope:
- `status != "success"`
- `conforms_to_plan == false`
- non-empty `errors[]` or `deviations[]`

Any hit → **HALT**. Use `AskUserQuestion`:
- **Accept deviation** — user confirms; orchestrator updates Sections 6-8 to match reality
- **Abort** — pipeline stops; user fixes sources or refactor decisions; restart

For silver builders specifically: every envelope's `read_bronze_only` must be `true`. Any `false` → halt (silver contract broken).

## Why the conformance gate matters

Without strict gates, a builder can silently drop a query, slip in a forbidden `spark.read.csv`, or generate invalid PySpark — and the pipeline reports "success" even though the migration is broken. The gate catches contract violations at the seam, with full context, before the user touches a Fabric notebook.

## Failure escalation

When a non-builder stage fails (preflight, deployment, runtime validation), the orchestrator uses `AskUserQuestion`:
1. **Retry** — re-run the failed stage
2. **Skip** — mark as skipped in Section 11, proceed
3. **Abort** — write final state to `Migration Report.md` and exit

Every escalation is logged to Section 11 (Design Decisions Log).
