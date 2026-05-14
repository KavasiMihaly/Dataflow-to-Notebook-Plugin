#!/usr/bin/env python3
"""SessionStart hook — detects missing Fabric config and prints a setup banner.

Mitigates the dbt-plugin Finding 5 Problem B: userConfig prompts may not fire
on install. If they didn't, this hook surfaces the gap at every session start
so the user knows what to set before running /migrate-dataflows.

Contract:
  Input on stdin: SessionStart JSON event (we don't actually need the input)
  Output on stdout: optional banner text printed to the user's session
  Exit code: 0 always
"""

from __future__ import annotations

import json
import os
import sys


REQUIRED_KEYS = [
    ("CLAUDE_PLUGIN_OPTION_fabric_workspace_name", "Target Fabric workspace display name"),
    ("CLAUDE_PLUGIN_OPTION_bronze_lakehouse", "Bronze lakehouse name (default lh_bronze)"),
    ("CLAUDE_PLUGIN_OPTION_silver_lakehouse", "Silver lakehouse name (default lh_silver)"),
]

OPTIONAL_KEYS = [
    ("CLAUDE_PLUGIN_OPTION_fabric_workspace_id", "Target Fabric workspace GUID"),
    ("CLAUDE_PLUGIN_OPTION_source_workspace_id", "Source Power BI workspace GUID (Gen1 dataflows)"),
]


def main() -> int:
    try:
        # Drain stdin (Claude Code may send the SessionStart payload, we don't use it)
        try:
            sys.stdin.read()
        except Exception:
            pass

        missing_required = [k for k, _ in REQUIRED_KEYS if not os.environ.get(k)]
        missing_optional = [k for k, _ in OPTIONAL_KEYS if not os.environ.get(k)]

        # Only emit banner if any required value is missing — keeps quiet on configured installs
        if not missing_required:
            return 0

        lines = [
            "",
            "=== fabric-dataflow-migration-toolkit: Setup Required ===",
            "",
            "The plugin needs userConfig values before /migrate-dataflows can run.",
            "",
            "Missing (required):",
        ]
        for key, desc in REQUIRED_KEYS:
            if not os.environ.get(key):
                key_short = key.replace("CLAUDE_PLUGIN_OPTION_", "")
                lines.append(f"  - {key_short}: {desc}")

        if missing_optional:
            lines.append("")
            lines.append("Missing (optional — can also be supplied at runtime):")
            for key, desc in OPTIONAL_KEYS:
                if not os.environ.get(key):
                    key_short = key.replace("CLAUDE_PLUGIN_OPTION_", "")
                    lines.append(f"  - {key_short}: {desc}")

        lines.extend(
            [
                "",
                "How to set:",
                "  Option A: Run `/plugin` and re-trigger the install prompts",
                "  Option B: Edit ~/.claude/settings.json under",
                "           pluginConfigs[fabric-dataflow-migration-toolkit].options",
                "",
                "Or try without Fabric access:",
                "  /migrate-dataflows --sample --dry-run",
                "  (uses bundled sample dataflows; no workspace needed)",
                "",
                "==========================================================",
                "",
            ]
        )

        # Use additionalContext to inject the banner into the session
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n".join(lines),
            }
        }
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
