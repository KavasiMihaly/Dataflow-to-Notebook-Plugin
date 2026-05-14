---
name: fabric-notebook-deployer
description: Deploy multiple .ipynb notebook files to a Microsoft Fabric workspace in batch. Wraps the Fabric REST API (via `fab api`) for createOrUpdate notebook operations with optional folder placement. Supports dry-run, glob patterns, retry on rate-limit, and structured JSON output. Use when migrating multiple notebooks at once or as part of an orchestrated deployment pipeline.
allowed-tools: Bash Read Glob
---

# Fabric Notebook Deployer

Batch-deploy `.ipynb` notebooks to a Microsoft Fabric workspace via REST API. Designed for orchestrator-driven migrations where many notebooks need to land in one workspace with consistent configuration.

## Why a separate skill (vs. `fabric-cli-runner`)?

The `fabric-cli-runner` skill executes one `fab` command per call. For a 20-notebook migration, that's 20 separate orchestrator tool calls. This skill bundles the loop with retry/log/dry-run behavior so the orchestrator delegates one batch operation.

## Prerequisites

- `fab` CLI installed and authenticated (`fab auth login` interactively, or service-principal env vars set)
- Target Fabric workspace exists and the authenticated identity has Contributor or higher

## Usage

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-notebook-deployer/scripts/deploy_notebooks.py" \
  --workspace "Analytics Dev" \
  --pattern "3 - Notebooks/**/*.ipynb"
```

### Dry-run mode

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-notebook-deployer/scripts/deploy_notebooks.py" \
  --workspace "Analytics Dev" \
  --pattern "3 - Notebooks/**/*.ipynb" \
  --dry-run
```

In dry-run, the script enumerates the files that WOULD be deployed and validates each is parseable JSON, but does not call the Fabric API. Useful for validating notebook generation before incurring deployment cost.

### Folder placement

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-notebook-deployer/scripts/deploy_notebooks.py" \
  --workspace "Analytics Dev" \
  --pattern "3 - Notebooks/bronze/*.ipynb" \
  --folder-id "<folder_GUID>"
```

If `--folder-id` is set, each deployed notebook is moved to that folder after creation.

### JSON output

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/fabric-notebook-deployer/scripts/deploy_notebooks.py" \
  --workspace "Analytics Dev" \
  --pattern "3 - Notebooks/**/*.ipynb" \
  --json
```

Outputs a single JSON object summarizing the run:

```json
{
  "status": "success|partial|failed",
  "mode": "deploy|dry-run",
  "workspace": "...",
  "deployed": [{"path": "...", "name": "...", "notebook_id": "..."}],
  "skipped": [{"path": "...", "reason": "..."}],
  "failed": [{"path": "...", "error": "..."}],
  "summary": {"total": N, "deployed_count": N, "skipped_count": N, "failed_count": N}
}
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--workspace` | yes | Fabric workspace display name |
| `--pattern` | yes | Glob pattern for `.ipynb` files (relative to cwd) |
| `--folder-id` | no | If set, move each deployed notebook to this folder GUID |
| `--dry-run` | no | Validate JSON only, do not deploy |
| `--json` | no | Emit a single JSON envelope to stdout (otherwise human-readable progress) |
| `--retry-count` | no | Retries on rate-limit errors (default 3) |
| `--retry-wait` | no | Seconds between retries (default 5) |
| `--name-from` | no | `filename` (default — strip .ipynb) or `metadata-title` (read from notebook metadata) |

## Authentication

The skill inherits authentication from the `fab` CLI. Either:

- **Interactive:** Run `fab auth login` once before invoking the skill.
- **Service principal:** Set env vars `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`. The plugin's userConfig values (`azure_*`) auto-map to these via the helper in the script.

## Behavior

1. **Enumerate** — glob the pattern, sort alphabetically (deterministic ordering).
2. **Validate JSON** — each file is parsed; invalid JSON is recorded as `failed` and skipped.
3. **Deploy** — for each valid notebook:
   - Read .ipynb content, base64-encode the JSON
   - Build the Fabric API payload (`{ "displayName": ..., "definition": { "parts": [...] } }`)
   - POST via `fab api` to `/v1/workspaces/<workspace>/notebooks`
   - On success, record the new notebook's ID
   - On rate limit (HTTP 429), retry up to `--retry-count` times
   - On other errors, record and continue (do not halt the batch)
4. **Folder placement** (optional) — if `--folder-id` set, PATCH each notebook to assign it to the folder.
5. **Report** — emit JSON or human-readable summary.

## Failure handling

The script never raises. Every error is captured in the `failed[]` list. The final exit code:
- `0` if all notebooks deployed successfully
- `1` if any deployment failed
- `2` if input validation failed (e.g., workspace not found, pattern matched zero files)

The orchestrator should read the JSON envelope to decide next steps.
