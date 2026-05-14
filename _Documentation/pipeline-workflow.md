# Pipeline Workflow — Process Map

**Last updated:** 2026-05-02
**Applies to:** `fabric-dataflow-migration-toolkit` plugin v0.1

This document is the authoritative narrative of the 13-stage migration pipeline. The orchestrator's `agent.md` is the implementation; this is the process map and contract reference for plugin contributors.

## Audience

- **Plugin users** — understand what will happen before approving the plan
- **Plugin contributors** — understand how stages fit together so a change to one doesn't break the contract the next depends on

## Invocation

```
/migrate-dataflows                       # full migration with deployment
/migrate-dataflows --dry-run             # generate notebooks, skip deployment
/migrate-dataflows --sample --dry-run    # bundled samples, no Fabric access
```

Or directly:

```bash
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows"
```

The orchestrator runs in the user's working directory. All paths are relative to cwd unless absolute.

## User interaction budget

Three interactive touchpoints. Everything else autonomous.

1. **Stage 1: Config Q&A** — workspace + lakehouse selections (skipped if userConfig set)
2. **Stage 5: Refactor decisions** — dynamic 3-4 questions via `migration-analyst`
3. **Stage 6: Plan approval** — native plan-mode summary

A fourth conditional touchpoint: **deviation escalation** at Stages 8, 9, or 10 if a builder/deployer can't satisfy its prompt. Only fires on contract breaks — clean runs never hit it.

## The master document

All design decisions, plans, build outputs, and validation results live in **`1 - Documentation/migration-design.md`**. Every stage reads it; specialists return JSON envelopes that the orchestrator merges into specific sections.

### Section ownership

| Section | Owner | When written |
|---|---|---|
| 0. Configuration | orchestrator | Stage 1 |
| 1. Migration Goals | `migration-analyst` direct | Stage 5 |
| 2. Dataflow Inventory | orchestrator from m-query-analyst JSON | Stage 3 |
| 3. Risk Catalog | orchestrator from m-query-analyst JSON | Stage 4 |
| 4. Dependency Map | orchestrator from m-query-analyst JSON | Stage 3 |
| 5. Refactor Decisions | `migration-analyst` direct | Stage 5 |
| 6. Medallion Mapping | orchestrator | Stage 5 |
| 7. Bronze Build Plan | orchestrator drafts; bronze builders fill rows | Stage 5 + 8 |
| 8. Silver Build Plan | orchestrator drafts; silver builders fill rows | Stage 5 + 9 |
| 9. Created Notebooks Registry | orchestrator | After every successful build |
| 10. Validation Results | `fabric-pipeline-validator` direct | Stage 12 |
| 11. Design Decisions Log | orchestrator | Throughout |
| 12. Migration Report | orchestrator | Stage 13 |

## The 13 stages (summary)

| Stage | Owner | Mode | Side effects |
|---|---|---|---|
| Pre | `fabric-preflight-check` | Auto | Fail fast if `fab` / `az login` missing |
| 0 | Orchestrator | Auto | Detect fresh build vs incremental |
| 1 | Orchestrator | Interactive | Ask config (workspace, lakehouses) |
| 2 | `dataflow-gen1-extractor` | Interactive (PowerShell auth) | Export Gen1 JSON → parse to .pq files |
| 3 | `m-query-analyst` Pass 1 | Background | Inventory, classification, dependency map |
| 4 | `m-query-analyst` Pass 2 | Background | Risk catalog scan; backlog entries for unknowns |
| 5 | `migration-analyst` | Interactive | Refactor + strategy decisions |
| 6 | Orchestrator | Plan mode | User approves medallion mapping |
| 7 | `fabric-project-initializer` | Auto | Project scaffolding |
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
