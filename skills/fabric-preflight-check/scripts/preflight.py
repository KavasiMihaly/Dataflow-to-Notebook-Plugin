#!/usr/bin/env python3
"""
Fabric Pre-flight Check

Verify Fabric CLI + Azure auth + (optionally) workspace/lakehouse access.
Returns 0 if all checks pass, 1 if any fail.

Usage:
  python preflight.py
  python preflight.py --workspace "Analytics Dev" --bronze-lakehouse "lh_bronze"
  python preflight.py --workspace "..." --json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys


def _load_plugin_userconfig_env():
    """Map Claude Code plugin userConfig values to FABRIC_* env vars."""
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


def run_cmd(cmd: list, timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out"
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"


def check_fab_installed() -> dict:
    if shutil.which("fab") is None:
        return {
            "name": "fab_installed",
            "pass": False,
            "detail": "fab CLI not on PATH",
            "remediation": "pip install ms-fabric-cli",
        }
    rc, out, err = run_cmd(["fab", "--version"])
    if rc != 0:
        return {
            "name": "fab_installed",
            "pass": False,
            "detail": err or out or "fab --version failed",
            "remediation": "pip install --upgrade ms-fabric-cli",
        }
    version = out.strip()
    return {"name": "fab_installed", "pass": True, "detail": version}


def check_azure_auth() -> dict:
    # Service principal env vars take precedence
    sp_keys = ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET")
    sp_set = all(os.environ.get(k) for k in sp_keys)
    if sp_set:
        return {"name": "azure_auth", "pass": True, "detail": "service principal (env vars set)"}

    # Otherwise try az cli
    if shutil.which("az") is None:
        return {
            "name": "azure_auth",
            "pass": False,
            "detail": "no service-principal env vars set and az CLI not found",
            "remediation": "Either set FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET; or install az CLI and run `az login`",
        }
    rc, out, err = run_cmd(["az", "account", "show"], timeout=15)
    if rc != 0:
        return {
            "name": "azure_auth",
            "pass": False,
            "detail": "az account show failed (likely not logged in)",
            "remediation": "Run `az login` interactively, or set FABRIC_TENANT_ID/FABRIC_CLIENT_ID/FABRIC_CLIENT_SECRET",
        }
    return {"name": "azure_auth", "pass": True, "detail": "interactive (az cli)"}


def check_workspace(workspace: str) -> dict:
    rc, out, err = run_cmd(["fab", "ls"], timeout=30)
    if rc != 0:
        return {
            "name": "workspace_access",
            "pass": False,
            "detail": f"fab ls failed: {err or out}",
            "remediation": "Verify auth is current; the authenticated identity may not have any workspace access",
        }
    # `fab ls` lists workspaces; check the target appears
    if workspace not in out:
        return {
            "name": "workspace_access",
            "pass": False,
            "detail": f"workspace '{workspace}' not found in fab ls output",
            "remediation": f"Verify '{workspace}' exists and matches the display name exactly. Check Contributor access.",
        }
    return {"name": "workspace_access", "pass": True, "detail": workspace}


def check_lakehouse(workspace: str, lakehouse: str, label: str) -> dict:
    rc, out, err = run_cmd(["fab", "ls", workspace, "--type", "Lakehouse"], timeout=30)
    if rc != 0:
        return {
            "name": label,
            "pass": False,
            "detail": f"fab ls failed: {err or out}",
            "remediation": "Re-check workspace access; lakehouse listing requires read access on the workspace",
        }
    if lakehouse not in out:
        return {
            "name": label,
            "pass": False,
            "detail": f"lakehouse '{lakehouse}' not found in workspace '{workspace}'",
            "remediation": f"Either create '{lakehouse}' in the Fabric portal first, or let migration Stage 7 scaffolding create it",
        }
    return {"name": label, "pass": True, "detail": lakehouse}


def main():
    parser = argparse.ArgumentParser(description="Pre-flight check for fabric-dataflow-migration-toolkit")
    parser.add_argument("--workspace", default=None, help="Optional: verify workspace exists")
    parser.add_argument("--bronze-lakehouse", default=None, help="Optional: verify bronze lakehouse exists")
    parser.add_argument("--silver-lakehouse", default=None, help="Optional: verify silver lakehouse exists")
    parser.add_argument("--json", action="store_true", help="Output JSON envelope")
    args = parser.parse_args()

    checks = []
    checks.append(check_fab_installed())
    if checks[-1]["pass"]:
        checks.append(check_azure_auth())
        if checks[-1]["pass"] and args.workspace:
            checks.append(check_workspace(args.workspace))
            if checks[-1]["pass"]:
                if args.bronze_lakehouse:
                    checks.append(check_lakehouse(args.workspace, args.bronze_lakehouse, "bronze_lakehouse"))
                if args.silver_lakehouse:
                    checks.append(check_lakehouse(args.workspace, args.silver_lakehouse, "silver_lakehouse"))

    all_pass = all(c["pass"] for c in checks)
    status = "ok" if all_pass else "fail"
    remediation = [c["remediation"] for c in checks if not c["pass"] and "remediation" in c]

    envelope = {"status": status, "checks": checks, "remediation": remediation}

    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        print("=== Fabric Pre-flight Check ===")
        for c in checks:
            mark = "PASS" if c["pass"] else "FAIL"
            print(f"  [{mark}] {c['name']}: {c['detail']}")
        if not all_pass:
            print("\n=== Remediation ===")
            for r in remediation:
                print(f"  - {r}")
        print(f"\nStatus: {status.upper()}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
