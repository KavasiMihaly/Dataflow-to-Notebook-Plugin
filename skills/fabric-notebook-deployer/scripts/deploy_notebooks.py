#!/usr/bin/env python3
"""
Fabric Notebook Deployer

Deploy one or many .ipynb files to a Microsoft Fabric workspace via REST API
(through `fab api`). Supports glob patterns, dry-run, retry on rate-limit, and
JSON output for orchestrator-driven workflows.

Usage:
  python deploy_notebooks.py --workspace "Analytics Dev" --pattern "3 - Notebooks/**/*.ipynb"
  python deploy_notebooks.py --workspace "..." --pattern "..." --dry-run --json
  python deploy_notebooks.py --workspace "..." --pattern "..." --folder-id "<GUID>"
"""

import argparse
import base64
import glob as globlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _load_plugin_userconfig_env():
    """Map Claude Code plugin userConfig values to FABRIC_* env vars.

    When this script is invoked from inside the fabric-dataflow-migration-toolkit
    plugin, Claude Code exports userConfig values as CLAUDE_PLUGIN_OPTION_<key>.
    The fab CLI reads FABRIC_TENANT_ID etc. — without this remap, SP auth fails
    silently when invoked from a plugin context.
    """
    mapping = {
        'FABRIC_TENANT_ID': 'azure_tenant_id',
        'FABRIC_CLIENT_ID': 'azure_client_id',
        'FABRIC_CLIENT_SECRET': 'azure_client_secret',
    }
    for key, plugin_key in mapping.items():
        if not os.environ.get(key):
            fallback = os.environ.get(f'CLAUDE_PLUGIN_OPTION_{plugin_key}')
            if fallback:
                os.environ[key] = fallback


_load_plugin_userconfig_env()


def fab_api(method: str, path: str, body: dict = None, timeout: int = 120) -> tuple[int, str, str]:
    """Invoke `fab api` with given method, path, and optional body. Returns (rc, stdout, stderr)."""
    cmd = ["fab", "api", "-X", method, path]
    if body is not None:
        cmd.extend(["-i", json.dumps(body)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "fab api call timed out"
    except FileNotFoundError:
        return 127, "", "fab CLI not found on PATH; run: pip install ms-fabric-cli"


def get_workspace_id(workspace_name: str) -> str | None:
    """Look up workspace GUID by display name."""
    rc, out, err = fab_api("GET", f"/v1/workspaces?displayName={workspace_name}")
    if rc != 0:
        return None
    try:
        data = json.loads(out)
        items = data.get("value", []) if isinstance(data, dict) else []
        for item in items:
            if item.get("displayName") == workspace_name:
                return item.get("id")
    except json.JSONDecodeError:
        pass
    return None


def deploy_notebook(workspace_id: str, notebook_path: Path, name: str, retry_count: int, retry_wait: int) -> tuple[str | None, str]:
    """Deploy one notebook. Returns (notebook_id_or_None, error_or_empty)."""
    try:
        with notebook_path.open("r", encoding="utf-8") as f:
            content = f.read()
        # Validate JSON
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or "cells" not in parsed:
            return None, f"Not a valid Jupyter notebook (missing cells)"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except Exception as e:
        return None, f"Read error: {e}"

    payload_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body = {
        "displayName": name,
        "definition": {
            "parts": [
                {
                    "path": "notebook-content.ipynb",
                    "payload": payload_b64,
                    "payloadType": "InlineBase64",
                }
            ]
        },
    }

    for attempt in range(retry_count + 1):
        rc, out, err = fab_api("POST", f"/v1/workspaces/{workspace_id}/notebooks", body=body)
        if rc == 0:
            try:
                data = json.loads(out)
                return data.get("id"), ""
            except json.JSONDecodeError:
                return None, f"Deployed but response not parseable: {out[:200]}"
        # Rate limit retry
        if "429" in (err or "") or "throttl" in (err or "").lower():
            if attempt < retry_count:
                time.sleep(retry_wait)
                continue
        return None, (err or out or "unknown error").strip()
    return None, "exhausted retries"


def move_to_folder(workspace_id: str, notebook_id: str, folder_id: str) -> str:
    """Move notebook to a folder. Returns error_or_empty."""
    body = {"folderId": folder_id}
    rc, out, err = fab_api("PATCH", f"/v1/workspaces/{workspace_id}/notebooks/{notebook_id}", body=body)
    if rc == 0:
        return ""
    return (err or out or "unknown move error").strip()


def main():
    parser = argparse.ArgumentParser(description="Deploy .ipynb notebooks to a Fabric workspace.")
    parser.add_argument("--workspace", required=True, help="Fabric workspace display name")
    parser.add_argument("--pattern", required=True, help="Glob pattern for .ipynb files")
    parser.add_argument("--folder-id", default=None, help="Optional folder GUID for placement")
    parser.add_argument("--dry-run", action="store_true", help="Validate without deploying")
    parser.add_argument("--json", action="store_true", help="Output single JSON envelope")
    parser.add_argument("--retry-count", type=int, default=3)
    parser.add_argument("--retry-wait", type=int, default=5)
    parser.add_argument(
        "--name-from",
        choices=["filename", "metadata-title"],
        default="filename",
        help="How to derive the displayName for each notebook",
    )
    args = parser.parse_args()

    files = sorted(globlib.glob(args.pattern, recursive=True))
    files = [f for f in files if f.endswith(".ipynb")]

    if not files:
        envelope = {
            "status": "failed",
            "mode": "dry-run" if args.dry_run else "deploy",
            "workspace": args.workspace,
            "deployed": [],
            "skipped": [],
            "failed": [],
            "summary": {"total": 0, "deployed_count": 0, "skipped_count": 0, "failed_count": 0},
            "error": f"Pattern matched zero .ipynb files: {args.pattern}",
        }
        if args.json:
            print(json.dumps(envelope, indent=2))
        else:
            print(f"ERROR: no .ipynb files match pattern: {args.pattern}")
        sys.exit(2)

    workspace_id = None
    if not args.dry_run:
        workspace_id = get_workspace_id(args.workspace)
        if not workspace_id:
            envelope = {
                "status": "failed",
                "mode": "deploy",
                "workspace": args.workspace,
                "deployed": [],
                "skipped": [],
                "failed": [{"path": "<workspace lookup>", "error": f"Workspace '{args.workspace}' not found"}],
                "summary": {"total": len(files), "deployed_count": 0, "skipped_count": 0, "failed_count": 1},
            }
            if args.json:
                print(json.dumps(envelope, indent=2))
            else:
                print(f"ERROR: workspace '{args.workspace}' not found")
            sys.exit(2)

    deployed = []
    skipped = []
    failed = []

    for f in files:
        path = Path(f)
        if args.name_from == "filename":
            name = path.stem
        else:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    nb = json.load(fh)
                name = nb.get("metadata", {}).get("title") or path.stem
            except Exception:
                name = path.stem

        if args.dry_run:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    json.load(fh)
                deployed.append({"path": str(path), "name": name, "notebook_id": None, "mode": "dry-run-validated"})
                if not args.json:
                    print(f"[DRY-RUN] OK  {path}")
            except Exception as e:
                failed.append({"path": str(path), "error": f"Invalid JSON: {e}"})
                if not args.json:
                    print(f"[DRY-RUN] FAIL {path}: {e}")
            continue

        notebook_id, err = deploy_notebook(workspace_id, path, name, args.retry_count, args.retry_wait)
        if notebook_id:
            entry = {"path": str(path), "name": name, "notebook_id": notebook_id}
            if args.folder_id:
                move_err = move_to_folder(workspace_id, notebook_id, args.folder_id)
                entry["folder_move_error"] = move_err if move_err else None
            deployed.append(entry)
            if not args.json:
                print(f"DEPLOYED {name} -> {notebook_id}")
        else:
            failed.append({"path": str(path), "error": err})
            if not args.json:
                print(f"FAILED {name}: {err}")

    status = "success" if not failed else ("partial" if deployed else "failed")
    envelope = {
        "status": status,
        "mode": "dry-run" if args.dry_run else "deploy",
        "workspace": args.workspace,
        "deployed": deployed,
        "skipped": skipped,
        "failed": failed,
        "summary": {
            "total": len(files),
            "deployed_count": len(deployed),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
        },
    }

    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        s = envelope["summary"]
        print(f"\n=== Summary ===")
        print(f"Total: {s['total']}, Deployed: {s['deployed_count']}, Failed: {s['failed_count']}")

    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
