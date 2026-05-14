#!/usr/bin/env python3
"""
Fabric CLI Runner Script

Executes fab commands and captures output for Claude Code integration.
Usage: python run_fabric_cli.py <fab_command> [args...]

Examples:
    python run_fabric_cli.py auth login
    python run_fabric_cli.py ls MyWorkspace
    python run_fabric_cli.py ls MyWorkspace --type Notebook
    python run_fabric_cli.py import MyWorkspace/nb_bronze.Notebook -i notebook.py
    python run_fabric_cli.py job run MyWorkspace/nb_bronze.Notebook
    python run_fabric_cli.py job run-status MyWorkspace/nb_bronze.Notebook --run-id <id>
    python run_fabric_cli.py cp local.csv MyWorkspace/lakehouse.Lakehouse/Files/
    python run_fabric_cli.py rm MyWorkspace/nb_old.Notebook -f
    python run_fabric_cli.py api get /v1/workspaces
"""

import sys
import subprocess
import os
from pathlib import Path


def find_project_config():
    """
    Find project-config.yml by walking up from current directory.
    Returns the config path and workspace name if found.
    """
    current = Path.cwd()

    for path in [current] + list(current.parents):
        config_file = path / "0 - Architecture Setup" / "project-config.yml"
        if config_file.exists():
            # Extract workspace name from config
            workspace = None
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("workspace_name:"):
                            workspace = line.split(":", 1)[1].strip().strip('"').strip("'")
                            break
            except Exception:
                pass
            return config_file, workspace

    return None, None


def check_fab_installed():
    """Verify fab CLI is available."""
    try:
        result = subprocess.run(
            ["fab", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        return False


def run_fab_command(args):
    """
    Execute fab command with provided arguments.

    Args:
        args: List of command arguments (e.g., ['ls', 'MyWorkspace'])

    Returns:
        int: Exit code from fab
    """
    # Show project context if available
    config_path, workspace = find_project_config()
    if config_path:
        print(f"[INFO] Project config: {config_path}")
        if workspace:
            print(f"[INFO] Workspace: {workspace}")

    # Auto-add --output_format json for job subcommands (machine-parseable)
    fab_args = list(args)
    if (
        len(fab_args) >= 2
        and fab_args[0] == "job"
        and "--output_format" not in fab_args
    ):
        fab_args.append("--output_format")
        fab_args.append("json")

    # Build fab command
    fab_cmd = ["fab"] + fab_args

    print(f"Executing: {' '.join(fab_cmd)}")
    print("-" * 80)

    try:
        result = subprocess.run(
            fab_cmd,
            capture_output=False,  # Stream output to console
            text=True
        )

        print("-" * 80)

        if result.returncode == 0:
            print(f"✓ fab {args[0]} completed successfully")
        else:
            print(f"✗ fab {args[0]} failed with exit code {result.returncode}")

        return result.returncode

    except FileNotFoundError:
        print("ERROR: fab command not found")
        print("Please install the Fabric CLI:")
        print("  pip install ms-fabric-cli")
        print("")
        print("Then authenticate:")
        print("  fab auth login")
        return 1

    except Exception as e:
        print(f"ERROR: Unexpected error running fab command: {e}")
        return 1


def main():
    """Main entry point for the script."""

    # Check if arguments provided
    if len(sys.argv) < 2:
        print("Usage: python run_fabric_cli.py <fab_command> [args...]")
        print("")
        print("Authentication:")
        print("  python run_fabric_cli.py auth login")
        print("  python run_fabric_cli.py auth status")
        print("")
        print("Deploy Notebooks:")
        print("  python run_fabric_cli.py import MyWorkspace/nb_name.Notebook -i notebook.py")
        print("")
        print("Run Notebooks:")
        print("  python run_fabric_cli.py job run MyWorkspace/nb_name.Notebook")
        print("  python run_fabric_cli.py job run MyWorkspace/nb_name.Notebook -P param:type=value")
        print("")
        print("Job Status:")
        print("  python run_fabric_cli.py job run-status MyWorkspace/nb_name.Notebook --run-id <id>")
        print("  python run_fabric_cli.py job run-list MyWorkspace/nb_name.Notebook")
        print("")
        print("List & Inspect:")
        print("  python run_fabric_cli.py ls")
        print("  python run_fabric_cli.py ls MyWorkspace")
        print("  python run_fabric_cli.py ls MyWorkspace --type Notebook")
        print("  python run_fabric_cli.py get MyWorkspace/nb_name.Notebook")
        print("")
        print("File Operations:")
        print("  python run_fabric_cli.py cp local.csv MyWorkspace/lakehouse.Lakehouse/Files/")
        print("  python run_fabric_cli.py rm MyWorkspace/nb_old.Notebook -f")
        print("")
        print("API:")
        print("  python run_fabric_cli.py api get /v1/workspaces")
        return 1

    # Check fab is installed
    if not check_fab_installed():
        print("ERROR: Fabric CLI (fab) is not installed")
        print("Install with: pip install ms-fabric-cli")
        print("Requires: Python 3.10 - 3.13")
        return 1

    # Get fab command and arguments
    fab_args = sys.argv[1:]

    # Execute fab command
    exit_code = run_fab_command(fab_args)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
