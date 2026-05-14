# Quickstart — Try the plugin without a Power BI workspace

This walkthrough runs the full migration pipeline against bundled sample dataflows in **dry-run mode**. No Fabric workspace, no Power BI access, no Azure auth needed. You'll see exactly what the plugin generates before pointing at production data.

---

## What you'll see

By the end, you'll have:
- 2 dataflow JSON files extracted into `.pq` query files
- An inventory document with classification, risk catalog, and dependency map
- A medallion mapping (bronze/silver/skip) for every query
- 4 generated `.ipynb` notebooks (2 bronze, 2 silver) — including HIGH RISK isolation cells for the patterns the converter can't fully automate
- A migration report

Total runtime: 3-5 minutes.

---

## Prerequisites

Just Python 3.10+. No `fab` CLI, no `az login`, no Power BI workspace required for `--sample --dry-run`.

If you've installed the plugin via marketplace, you're already set.

---

## Steps

### 1. Open or create a working folder

The plugin needs a working directory. Create an empty one and `cd` into it:

```bash
mkdir ~/fabric-migration-test
cd ~/fabric-migration-test
```

### 2. Launch the orchestrator as the main agent

From a **fresh shell** (not from inside an existing Claude session), run:

```bash
claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate sample dataflows. Flags: --sample --dry-run"
```

The orchestrator must run as the main Claude session, not as a subagent. It delegates to 5 specialist subagents (`m-query-analyst`, `migration-analyst`, `fabric-bronze-builder`, `fabric-silver-builder`, `fabric-pipeline-validator`), and Claude Code's hierarchy rules prevent a subagent from spawning further subagents — so the orchestrator must be the main thread for its delegation to work.

### 3. Walk through the 13 stages

The orchestrator will:

- **Pre / Stage 0:** Skip preflight (sample mode); detect this is a fresh build
- **Stage 1:** Skip config Q&A (sample mode auto-fills with placeholder workspace)
- **Stage 2:** Copy bundled JSONs from `${CLAUDE_PLUGIN_ROOT}/examples/sample-dataflows/` to `1 - Source Dataflows/`, parse to `.pq` files in `2 - Source Files/m_queries/`
- **Stage 3:** `m-query-analyst` runs Pass 1 → produces `1 - Documentation/m-analysis-inventory.json`
- **Stage 4:** `m-query-analyst` runs Pass 2 → produces `1 - Documentation/m-analysis-risks.json`
- **Stage 5:** `migration-analyst` asks 3-4 questions (in dry-run mode, defaults are pre-selected — you'll see the questions but can accept defaults)
- **Stage 6:** Plan-mode summary appears. Review and approve.
- **Stage 7:** Project scaffolding — creates `0 - Architecture Setup/`, `3 - Notebooks/{bronze,silver,gold}/`, etc.
- **Stage 8:** `fabric-bronze-builder` generates `nb_bronze_schools.ipynb`, `nb_bronze_ofsted_rating.ipynb`, `nb_bronze_population_trend.ipynb`, `nb_bronze_population_estimates_2020.ipynb`
- **Stage 9:** `fabric-silver-builder` generates `nb_silver_schools.ipynb`, `nb_silver_population_trend.ipynb` (silver layer for queries that did transformations)
- **Stage 10:** SKIPPED (dry-run)
- **Stage 11:** SKIPPED (dry-run)
- **Stage 12:** `fabric-pipeline-validator` runs static checks only (no lakehouse queries)
- **Stage 13:** Writes `Migration Report.md`

### 4. Inspect the output

After completion:

```bash
ls "3 - Notebooks/bronze/"
# nb_bronze_ofsted_rating.ipynb
# nb_bronze_population_estimates_2020.ipynb
# nb_bronze_population_trend.ipynb
# nb_bronze_schools.ipynb
```

Open `nb_bronze_population_estimates_2020.ipynb` — you'll see a HIGH RISK / HUMAN REVIEW REQUIRED cell because the source uses `Excel.Workbook` (RISK-03), which has no native PySpark equivalent. The converter emits best-effort pandas+openpyxl code with a clear review marker.

Open `Migration Report.md`:

```markdown
# Migration Report — Sample dataflows
Mode: Dry Run — no deployment performed

Notebooks generated:
- Bronze: 4
- Silver: 2
- Skipped (helpers): 1

Risk-isolated cells: 3 (across 2 notebooks)
- nb_bronze_population_estimates_2020.ipynb: 1 cell (RISK-03 Excel.Workbook)
- nb_bronze_population_trend.ipynb: 1 cell (RISK-01 AzureStorage.Blobs)
- nb_bronze_schools.ipynb: 1 cell (RISK-01 AzureStorage.Blobs)
```

Open `1 - Documentation/migration-design.md` — the full design doc with all 12 sections populated.

---

## Next steps

Now that you've seen the output shape:

1. **Review the HIGH RISK cells** — these are the spots that need manual attention. Update them based on your storage configuration.
2. **Adjust refactor decisions** — re-run with different answers at Stage 5 to see how output changes (e.g., `Combine Files: preserve` vs `absorb`).
3. **Point at production** — set your real workspace ID via `/plugin` config, then launch from a fresh shell with no flags: `claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows from workspace <GUID>"`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Pattern matched zero .pq files" at Stage 3 | Verify `2 - Source Files/m_queries/` exists with files. Sample mode should auto-create these. |
| Plan-mode summary shows zero notebooks | Stage 5 refactor decisions may have set `helpers: preserve` for everything. Re-run and pick `absorb`. |
| Validator FAILs on silver "no read_bronze() found" | A silver notebook bypassed bronze — the validator caught it. Re-run; the silver-builder agent has a hard rule about this. |

If the orchestrator stalls or shows "I'm unable to execute Bash commands", the plugin's `approve-plugin-bash.py` hook isn't firing. Check `/hooks` to confirm the hook is registered, then `/reload-plugins`.
