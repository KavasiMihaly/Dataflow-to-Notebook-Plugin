---
name: fabric-preflight-check
description: Pre-flight validation for the fabric-dataflow-migration-toolkit. Verifies that the Fabric CLI (`fab`) is installed and authenticated, that Azure auth is current, and (optionally) that a target workspace + lakehouses exist and are accessible. Use BEFORE running long migrations to fail fast on auth/config issues. Outputs human-readable status or a JSON envelope for orchestrator integration.
allowed-tools: Bash Read
---

# Fabric Pre-flight Check

Before running a 20-minute migration that fails at deploy time on `az login expired`, this skill checks every prerequisite in seconds and prints a clear remediation message if anything is wrong.

## Why use this skill

The orchestrator runs Stage Pre with this skill. If it fails, the orchestrator halts immediately — no time wasted on extraction, analysis, generation, only to fail at Stage 10 deployment. Users avoid the worst-case "everything looked fine until the last 30 seconds" pattern.

## What it checks

| Check | What | Pass criteria |
|---|---|---|
| `fab_installed` | `fab --version` returns 0 | Exit code 0, version >= 0.1.0 |
| `azure_auth` | `az account show` OR service-principal env vars set | Exit code 0, or all 3 SP env vars present |
| `workspace_access` (optional) | `fab cd <workspace>` resolves | Exit code 0 |
| `bronze_lakehouse` (optional) | `fab get <workspace>/<bronze>.Lakehouse` returns 0 | Exit code 0 |
| `silver_lakehouse` (optional) | same for silver lakehouse | Exit code 0 |

The optional checks run only if the relevant env var / argument is provided.

## Usage

### Basic — just check tools and auth

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-preflight-check/scripts/preflight.py"
```

### Full — check workspace and lakehouses too

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-preflight-check/scripts/preflight.py" \
  --workspace "Analytics Dev" \
  --bronze-lakehouse "lh_bronze" \
  --silver-lakehouse "lh_silver"
```

### JSON output for orchestrator

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-preflight-check/scripts/preflight.py" \
  --workspace "Analytics Dev" \
  --json
```

JSON envelope:

```json
{
  "status": "ok|fail",
  "checks": [
    {"name": "fab_installed", "pass": true, "detail": "fab v0.x.x"},
    {"name": "azure_auth", "pass": true, "detail": "interactive (az cli)"},
    {"name": "workspace_access", "pass": true, "detail": "Analytics Dev"}
  ],
  "remediation": ["...if any check failed, ordered list of fix steps"]
}
```

## Remediation messages

If a check fails, the script prints a clear remediation step:

| Failure | Remediation |
|---|---|
| `fab` not found | `pip install ms-fabric-cli` |
| `fab` outdated | `pip install --upgrade ms-fabric-cli` |
| `az login` expired | `az login` (interactive) OR set `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET` env vars |
| Workspace not found | Verify `--workspace` matches the display name exactly; check that the authenticated identity has Contributor access |
| Lakehouse not found | Either create it in the Fabric portal first, or let the migration's Stage 7 scaffolding create it |

## Exit codes

- `0` — all checks passed (`status: ok`)
- `1` — at least one check failed (`status: fail`)
- `2` — script error (e.g., bad arguments)
