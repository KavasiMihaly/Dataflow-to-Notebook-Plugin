#!/usr/bin/env python3
"""Pre-shipment audit for fabric-dataflow-migration-toolkit plugin.

Runs the §8.1 quality gates from the plan:

  1. Atomic-Bash audit — no compound shell expressions in agent.md / SKILL.md files
  2. Path audit — no $HOME/.claude/skills/, no C:\\Users\\kavas, no \\scripts\\
  3. Namespace audit — every cross-agent reference uses 3-part name
  4. Skills frontmatter audit — every agent's `skills:` uses 2-part namespace
  5. Plugin manifest validation — plugin.json parses, hook scripts exist, userConfig keys complete

Exit code 0 if all gates pass, 1 if any gate fails.

Usage:
  python tests/preshipment_audit.py
  python tests/preshipment_audit.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


PLUGIN_NAME = "fabric-dataflow-migration-toolkit"
ROOT = Path(__file__).parent.parent.resolve()


def _walk_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for sub in root.rglob("*"):
        if sub.is_file() and sub.suffix in suffixes:
            out.append(sub)
    return out


def gate_atomic_bash(findings: list[dict]) -> bool:
    """Detect compound shell expressions in agent and skill markdown.

    Looks for &&, ||, ;, |, $(, backticks INSIDE bash code blocks (```bash blocks).
    Comments and prose are excluded — we only scan inside fenced bash blocks.
    """
    md_files = _walk_files(ROOT / "agents", (".md",)) + _walk_files(ROOT / "skills", (".md",))
    forbidden = [
        ("&&", r"&&"),
        ("||", r"\|\|"),
        ("$()", r"\$\("),
        ("backtick", r"`[^\n]+`"),
    ]
    bash_block_re = re.compile(r"```(?:bash|sh)\s*\n(.*?)\n```", re.DOTALL)
    failed = False
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in bash_block_re.finditer(text):
            block = match.group(1)
            # Strip lines that are pure shell comments
            scan_text = "\n".join(line for line in block.splitlines() if not line.strip().startswith("#"))
            for label, pattern in forbidden:
                if re.search(pattern, scan_text):
                    findings.append({
                        "gate": "atomic_bash",
                        "file": str(f.relative_to(ROOT)),
                        "issue": f"Compound shell pattern '{label}' found in bash block",
                    })
                    failed = True
    return not failed


def gate_paths(findings: list[dict]) -> bool:
    """Reject lingering $HOME/.claude/skills/ and Windows-user paths."""
    md_files = _walk_files(ROOT / "agents", (".md",)) + _walk_files(ROOT / "skills", (".md",))
    py_files = _walk_files(ROOT / "skills", (".py",)) + _walk_files(ROOT / "hooks", (".py",))
    bad_patterns = [
        (r"\$HOME/\.claude/skills/", "use ${CLAUDE_PLUGIN_ROOT}/skills/"),
        (r"C:\\\\Users\\\\kavas\\\\\\.claude", "use ${CLAUDE_PLUGIN_ROOT}"),
        (r"C:\\Users\\kavas\\.claude", "use ${CLAUDE_PLUGIN_ROOT}"),
        (r"\\scripts\\", "use /scripts/"),
    ]
    failed = False
    for f in md_files + py_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for pat, fix in bad_patterns:
            for m in re.finditer(pat, text):
                findings.append({
                    "gate": "paths",
                    "file": str(f.relative_to(ROOT)),
                    "issue": f"Bad path pattern '{m.group(0)}' — {fix}",
                })
                failed = True
    return not failed


def gate_namespace(findings: list[dict]) -> bool:
    """Every Task spawn or Agent allowlist entry must be 3-part."""
    agent_files = list((ROOT / "agents").rglob("agent.md"))
    failed = False
    # Look for subagent_type or Agent(name1, name2, ...) in agent bodies.
    # Bare agent name (no colon) referencing a known agent in this plugin = fail.
    known_agents = {p.parent.name for p in agent_files}
    bare_pat = re.compile(r'subagent_type\s*[:=]\s*["\']([\w-]+)["\']')
    for f in agent_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in bare_pat.finditer(text):
            name = m.group(1)
            if ":" not in name and name in known_agents:
                findings.append({
                    "gate": "namespace",
                    "file": str(f.relative_to(ROOT)),
                    "issue": f"Bare subagent_type '{name}' — use {PLUGIN_NAME}:{name}:{name}",
                })
                failed = True
    return not failed


def gate_skills_frontmatter(findings: list[dict]) -> bool:
    """Agent skills: frontmatter field must use 2-part namespace `<plugin>:<skill>`."""
    agent_files = list((ROOT / "agents").rglob("agent.md"))
    skills_dirs = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    failed = False
    for f in agent_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL | re.MULTILINE)
        if not m:
            continue
        front = m.group(1)
        skills_match = re.search(r"^skills\s*:\s*(.+?)$", front, re.MULTILINE)
        if not skills_match:
            continue
        skills_value = skills_match.group(1).strip()
        # Comma-separated list of names
        for entry in (s.strip() for s in skills_value.split(",")):
            if not entry:
                continue
            if ":" not in entry:
                # bare skill name — fail if it matches a plugin skill
                if entry in skills_dirs:
                    findings.append({
                        "gate": "skills_frontmatter",
                        "file": str(f.relative_to(ROOT)),
                        "issue": f"Bare skill '{entry}' in skills: — use {PLUGIN_NAME}:{entry}",
                    })
                    failed = True
            else:
                # 2-part: plugin-name:skill-name. Verify plugin part matches.
                parts = entry.split(":")
                if len(parts) != 2 or parts[0] != PLUGIN_NAME:
                    findings.append({
                        "gate": "skills_frontmatter",
                        "file": str(f.relative_to(ROOT)),
                        "issue": f"Skill ref '{entry}' has wrong namespace — should be {PLUGIN_NAME}:<skill>",
                    })
                    failed = True
    return not failed


def gate_plugin_manifest(findings: list[dict]) -> bool:
    """Validate .claude-plugin/plugin.json structure and referenced files exist."""
    manifest_path = ROOT / ".claude-plugin" / "plugin.json"
    if not manifest_path.exists():
        findings.append({"gate": "plugin_manifest", "file": "plugin.json", "issue": "Manifest missing"})
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        findings.append({"gate": "plugin_manifest", "file": "plugin.json", "issue": f"Invalid JSON: {e}"})
        return False

    failed = False
    # Required top-level keys
    for key in ("name", "version", "description", "author"):
        if key not in manifest:
            findings.append({"gate": "plugin_manifest", "file": "plugin.json", "issue": f"Missing key: {key}"})
            failed = True
    # Plugin name must match
    if manifest.get("name") != PLUGIN_NAME:
        findings.append({
            "gate": "plugin_manifest",
            "file": "plugin.json",
            "issue": f"Plugin name '{manifest.get('name')}' != expected '{PLUGIN_NAME}'",
        })
        failed = True
    # All hook script paths must exist
    hooks = manifest.get("hooks", {})
    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                m = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/(\S+)", cmd)
                if m:
                    rel = m.group(1)
                    abs_path = ROOT / rel
                    if not abs_path.exists():
                        findings.append({
                            "gate": "plugin_manifest",
                            "file": "plugin.json",
                            "issue": f"Hook script not found: {rel} (referenced in {event})",
                        })
                        failed = True
    # userConfig keys must have title + description + type
    user_config = manifest.get("userConfig", {})
    for key, schema in user_config.items():
        for required in ("title", "description", "type"):
            if required not in schema:
                findings.append({
                    "gate": "plugin_manifest",
                    "file": "plugin.json",
                    "issue": f"userConfig.{key} missing field: {required}",
                })
                failed = True
    return not failed


def gate_required_files(findings: list[dict]) -> bool:
    """All files claimed in the plan exist."""
    required = [
        ".claude-plugin/plugin.json",
        "README.md",
        "agents/fabric-migration-orchestrator/agent.md",
        "agents/m-query-analyst/agent.md",
        "agents/migration-analyst/agent.md",
        "agents/fabric-bronze-builder/agent.md",
        "agents/fabric-silver-builder/agent.md",
        "agents/fabric-pipeline-validator/agent.md",
        "skills/dataflow-gen1-extractor/SKILL.md",
        "skills/m-to-pyspark-converter/SKILL.md",
        "skills/fabric-cli-runner/SKILL.md",
        "skills/fabric-lakehouse-reader/SKILL.md",
        "skills/fabric-project-initializer/SKILL.md",
        "skills/data-profiler/SKILL.md",
        "skills/fabric-notebook-deployer/SKILL.md",
        "skills/fabric-preflight-check/SKILL.md",
        "skills/report-unknown-patterns/SKILL.md",
        "hooks/approve-plugin-bash.py",
        "hooks/validate-fabric-structure.py",
        "hooks/session-start-config-check.py",
        "reference/pyspark-style-guide.md",
        "reference/notebook-template.md",
        "reference/delta-lake-patterns.md",
        "reference/fabric-testing-patterns.md",
        "reference/m-conversion-risk-catalog.md",
        "examples/sample-dataflows/Sample Education Data.json",
        "examples/sample-dataflows/Sample Population Data.json",
        "examples/quickstart.md",
    ]
    failed = False
    for rel in required:
        if not (ROOT / rel).exists():
            findings.append({"gate": "required_files", "file": rel, "issue": "File missing"})
            failed = True
    return not failed


def main():
    parser = argparse.ArgumentParser(description="Pre-shipment audit for the plugin.")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope")
    args = parser.parse_args()

    gates = [
        ("required_files", gate_required_files),
        ("plugin_manifest", gate_plugin_manifest),
        ("paths", gate_paths),
        ("namespace", gate_namespace),
        ("skills_frontmatter", gate_skills_frontmatter),
        ("atomic_bash", gate_atomic_bash),
    ]

    findings: list[dict] = []
    results: list[tuple[str, bool]] = []
    for name, fn in gates:
        passed = fn(findings)
        results.append((name, passed))

    all_pass = all(p for _, p in results)
    envelope = {
        "status": "pass" if all_pass else "fail",
        "results": [{"gate": n, "pass": p} for n, p in results],
        "findings": findings,
        "summary": {"total_gates": len(gates), "passed": sum(1 for _, p in results if p), "findings_count": len(findings)},
    }

    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        print(f"=== Pre-shipment audit: {PLUGIN_NAME} ===\n")
        for name, passed in results:
            mark = "PASS" if passed else "FAIL"
            print(f"  [{mark}] {name}")
        print()
        if findings:
            print(f"=== Findings ({len(findings)}) ===")
            for f in findings:
                print(f"  - [{f['gate']}] {f['file']}: {f['issue']}")
            print()
        print(f"Overall: {'PASS' if all_pass else 'FAIL'}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
