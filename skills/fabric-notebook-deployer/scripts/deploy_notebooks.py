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


def fab_api(method: str, path: str, body: dict = None, timeout: int = 120) -> tuple[int, int, dict, str]:
    """Invoke `fab api` with given method, path, and optional body.

    Returns (rc, status_code, data, err) where:
      - rc          : the `fab` process exit code
      - status_code : the HTTP status from the response envelope (0 if unparseable)
      - data        : the unwrapped response payload (the envelope's "text", or {})
      - err         : stderr / parse-error string ("" on clean success)

    Compatible with fab (ms-fabric-cli) >= 1.6, which:
      * only accepts lowercase HTTP methods (get/post/patch/...),
      * prepends the Fabric base+version URL itself, so paths must NOT carry "/v1/",
      * wraps every response in {"status_code": <int>, "text": <payload>},
      * returns exit code 0 even for HTTP 4xx/5xx (error lives in the envelope).
    """
    # fab 1.6+ rejects uppercase methods: "invalid choice: 'GET'".
    cmd = ["fab", "api", "-X", method.lower(), path]
    if body is not None:
        cmd.extend(["-i", json.dumps(body)])
    # On a cp1252 Windows console, fab crashes printing non-ASCII (e.g. "✓"/"→").
    # Force UTF-8 in the child so it can emit its output without a charmap crash.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, 0, {}, "fab api call timed out"
    except FileNotFoundError:
        return 127, 0, {}, "fab CLI not found on PATH; run: pip install ms-fabric-cli"

    if result.returncode != 0 and not result.stdout.strip():
        return result.returncode, 0, {}, (result.stderr or "").strip()

    try:
        resp = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Some commands print plain text; surface it as-is with an unknown status.
        return result.returncode, 0, {}, (result.stderr or result.stdout or "").strip()

    if isinstance(resp, dict) and "status_code" in resp:
        status = resp.get("status_code", 0)
        data = resp.get("text", {})
    else:
        # Older fab versions returned the payload directly, with no envelope.
        status = 200
        data = resp
    if not isinstance(data, dict):
        data = {"value": data} if isinstance(data, list) else {"raw": data}
    err = "" if 200 <= status < 300 else json.dumps(data)[:300]
    return result.returncode, status, data, err


def get_workspace_id(workspace_name: str) -> str | None:
    """Look up workspace GUID by display name."""
    # fab 1.6 ignores ?displayName= filtering reliably, so list all and match locally.
    rc, status, data, err = fab_api("GET", "workspaces")
    if not (200 <= status < 300):
        return None
    items = data.get("value", []) if isinstance(data, dict) else []
    for item in items:
        if item.get("displayName") == workspace_name:
            return item.get("id")
    return None


def get_lakehouse_id(workspace_id: str, lakehouse_name: str, cache: dict) -> str | None:
    """Resolve a lakehouse GUID by display name within a workspace (cached per run)."""
    key = (workspace_id, lakehouse_name)
    if key in cache:
        return cache[key]
    rc, status, data, err = fab_api("GET", f"workspaces/{workspace_id}/items?type=Lakehouse")
    result = None
    if 200 <= status < 300:
        for item in (data.get("value", []) if isinstance(data, dict) else []):
            if item.get("displayName") == lakehouse_name:
                result = item.get("id")
                break
    cache[key] = result
    return result


def _is_placeholder(value: str | None) -> bool:
    """A templated, not-yet-resolved value such as '<bronze-lakehouse-name>' or a zero GUID."""
    if not value:
        return True
    return value.startswith("<") or set(value) <= {"0", "-"}


def bind_lakehouse(nb: dict, workspace_id: str, name_override: str | None,
                   id_override: str | None, cache: dict) -> tuple[bool, str]:
    """Rewrite nb['metadata']['dependencies']['lakehouse'] to point at a real lakehouse
    in the target workspace. Mutates nb in place. Returns (changed, note)."""
    block = nb.get("metadata", {}).get("dependencies", {}).get("lakehouse")
    if not isinstance(block, dict):
        return False, "no lakehouse dependency to bind"

    name = name_override or block.get("default_lakehouse_name")
    if id_override:
        lh_id = id_override
    else:
        if _is_placeholder(name):
            return False, f"unresolved lakehouse placeholder name '{name}' (pass --lakehouse-name)"
        lh_id = get_lakehouse_id(workspace_id, name, cache)
        if not lh_id:
            return False, f"lakehouse '{name}' not found in target workspace"

    block["default_lakehouse"] = lh_id
    block["known_lakehouses"] = [{"id": lh_id}]
    block["default_lakehouse_name"] = name
    block["default_lakehouse_workspace_id"] = workspace_id
    return True, f"bound '{name}' -> {lh_id}"


def deploy_notebook(workspace_id: str, content: str, name: str, retry_count: int, retry_wait: int) -> tuple[str | None, str]:
    """Deploy one notebook from its JSON content string. Returns (notebook_id_or_None, error_or_empty)."""
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
        rc, status, data, err = fab_api("POST", f"workspaces/{workspace_id}/notebooks", body=body)
        if 200 <= status < 300:
            # 201 returns the created item; 202 (LRO accepted) may have no id yet.
            return data.get("id") or data.get("displayName") or name, ""
        # Rate limit retry (429 surfaces in the envelope status on fab 1.6+).
        if status == 429 or "429" in (err or "") or "throttl" in (err or "").lower():
            if attempt < retry_count:
                time.sleep(retry_wait)
                continue
        return None, (err or "unknown error").strip()
    return None, "exhausted retries"


def move_to_folder(workspace_id: str, notebook_id: str, folder_id: str) -> str:
    """Move notebook to a folder. Returns error_or_empty."""
    body = {"folderId": folder_id}
    rc, status, data, err = fab_api("PATCH", f"workspaces/{workspace_id}/notebooks/{notebook_id}", body=body)
    if 200 <= status < 300:
        return ""
    return (err or "unknown move error").strip()


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
    parser.add_argument(
        "--resolve-lakehouse",
        action="store_true",
        help="At deploy time, resolve each notebook's lakehouse name to a real GUID in the "
             "target workspace and stamp in the workspace id (fixes placeholder/zero GUIDs).",
    )
    parser.add_argument(
        "--lakehouse-name",
        default=None,
        help="Override the lakehouse display name to bind for every notebook (implies "
             "--resolve-lakehouse). Use when notebooks still carry placeholder names.",
    )
    parser.add_argument(
        "--lakehouse-id",
        default=None,
        help="Bind this exact lakehouse GUID for every notebook (implies --resolve-lakehouse; "
             "skips the workspace lookup).",
    )
    args = parser.parse_args()

    bind_enabled = args.resolve_lakehouse or bool(args.lakehouse_name) or bool(args.lakehouse_id)

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
    lakehouse_cache = {}

    for f in files:
        path = Path(f)
        # Read + parse the notebook once; used for name derivation, validation, and binding.
        try:
            with path.open("r", encoding="utf-8") as fh:
                nb = json.load(fh)
            if not isinstance(nb, dict) or "cells" not in nb:
                raise ValueError("not a valid Jupyter notebook (missing cells)")
        except Exception as e:
            failed.append({"path": str(path), "error": f"Invalid JSON: {e}"})
            if not args.json:
                tag = "[DRY-RUN] FAIL" if args.dry_run else "FAILED"
                print(f"{tag} {path}: {e}")
            continue

        if args.name_from == "filename":
            name = path.stem
        else:
            name = nb.get("metadata", {}).get("title") or path.stem

        if args.dry_run:
            note = ""
            if bind_enabled:
                block = nb.get("metadata", {}).get("dependencies", {}).get("lakehouse")
                lh_name = args.lakehouse_name or (block.get("default_lakehouse_name") if isinstance(block, dict) else None)
                note = f" (would bind lakehouse '{lh_name}')" if (block or args.lakehouse_id) else " (no lakehouse to bind)"
            deployed.append({"path": str(path), "name": name, "notebook_id": None, "mode": "dry-run-validated"})
            if not args.json:
                print(f"[DRY-RUN] OK  {path}{note}")
            continue

        bind_note = ""
        if bind_enabled:
            changed, bind_note = bind_lakehouse(
                nb, workspace_id, args.lakehouse_name, args.lakehouse_id, lakehouse_cache)
            if not changed and ("not found" in bind_note or "placeholder" in bind_note):
                failed.append({"path": str(path), "error": f"Lakehouse binding failed: {bind_note}"})
                if not args.json:
                    print(f"FAILED {name}: lakehouse binding — {bind_note}")
                continue

        content = json.dumps(nb)
        notebook_id, err = deploy_notebook(workspace_id, content, name, args.retry_count, args.retry_wait)
        if notebook_id:
            entry = {"path": str(path), "name": name, "notebook_id": notebook_id}
            if bind_note:
                entry["lakehouse_binding"] = bind_note
            if args.folder_id:
                move_err = move_to_folder(workspace_id, notebook_id, args.folder_id)
                entry["folder_move_error"] = move_err if move_err else None
            deployed.append(entry)
            if not args.json:
                suffix = f"  [{bind_note}]" if bind_note else ""
                print(f"DEPLOYED {name} -> {notebook_id}{suffix}")
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
