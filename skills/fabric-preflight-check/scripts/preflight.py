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


def check_tls_interception() -> dict:
    """Probe whether Python's TLS stack trusts the chain served by a Microsoft endpoint.

    If the probe fails with an SSL verification error, there is almost certainly a
    corporate TLS-intercepting middlebox (Norton AV, Zscaler, Palo Alto, etc.)
    re-signing connections with a root CA that is in the Windows certificate store
    but NOT in Python's bundled certifi list. This breaks `az login`, `fab` CLI,
    `pip` against PyPI, and every other Python tool that uses `requests`.

    This check is **informational, not blocking** — it always returns pass=True so
    it does not halt the preflight. If interception is detected, the returned dict
    populates a `warning` field that the orchestrator surfaces to the user.

    The fix (when this fires): run `examples/Setup-CorpCertBundle.ps1` once and
    restart the shell. See README "Corporate environment setup".
    """
    try:
        import ssl
        import urllib.request
        import urllib.error
    except ImportError:
        return {"name": "tls_interception", "pass": True, "detail": "skipped (stdlib unavailable)"}

    probe_url = "https://api.fabric.microsoft.com/"
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(probe_url, method="HEAD")
        urllib.request.urlopen(req, context=ctx, timeout=10)
        return {
            "name": "tls_interception",
            "pass": True,
            "detail": f"Python TLS trust chain to {probe_url} OK — no interception detected",
        }
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        msg = str(reason).lower()
        if "certificate" in msg or "ssl" in msg or "cert verify" in msg or "self-signed" in msg or "unable to get local issuer" in msg:
            return {
                "name": "tls_interception",
                "pass": True,  # informational — don't block on this
                "detail": f"Python TLS verification failed against {probe_url}",
                "warning": (
                    "Corporate TLS interception detected. Python-based tools "
                    "(`az login`, `fab` CLI, `pip` against PyPI) will fail with SSL errors "
                    "at Stages 10–12 in live mode. Fix: run "
                    "`powershell -File examples\\Setup-CorpCertBundle.ps1` once to augment "
                    "Python's certifi bundle with the corporate root CA from the Windows "
                    "certificate store, then restart the shell. See README "
                    "\"Corporate environment setup\" for details. "
                    f"Underlying error: {reason}"
                ),
            }
        # Non-TLS error (DNS, network down, firewall block) — don't claim interception.
        return {
            "name": "tls_interception",
            "pass": True,
            "detail": f"could not probe {probe_url} ({reason}); skipping interception check",
        }
    except Exception as e:
        return {
            "name": "tls_interception",
            "pass": True,
            "detail": f"probe error ({type(e).__name__}: {e}); skipping",
        }


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
    # TLS interception check runs first because its remediation (Setup-CorpCertBundle.ps1)
    # is a prerequisite for the rest of the Python-based checks (az, fab) to succeed
    # in corporate environments. The check itself does NOT block — it always passes —
    # but emits a `warning` field that the orchestrator surfaces to the user.
    checks.append(check_tls_interception())
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
    warnings = [{"name": c["name"], "message": c["warning"]} for c in checks if c.get("warning")]

    envelope = {"status": status, "checks": checks, "remediation": remediation, "warnings": warnings}

    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        print("=== Fabric Pre-flight Check ===")
        for c in checks:
            mark = "PASS" if c["pass"] else "FAIL"
            print(f"  [{mark}] {c['name']}: {c['detail']}")
        if warnings:
            print("\n=== Warnings ===")
            for w in warnings:
                print(f"  - [{w['name']}] {w['message']}")
        if not all_pass:
            print("\n=== Remediation ===")
            for r in remediation:
                print(f"  - {r}")
        print(f"\nStatus: {status.upper()}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
