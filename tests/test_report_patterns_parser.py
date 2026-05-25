#!/usr/bin/env python3
"""Regression tests for report-unknown-patterns skill (issue #15).

Standalone test runner (no pytest dep). Exit 0 = all pass, 1 = any fail.

Covers:
  - parse_backlog handles `\\|` (escaped pipe) inside Sample M cells (bug 4)
  - get_repo_from_manifest falls back to plugin root when CLAUDE_PLUGIN_ROOT
    is unset (bug 2)
  - parse_backlog accepts both 'Backlog' and 'open' status sentinels
    (defense-in-depth for bug 1)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make the skill script importable as a module
ROOT = Path(__file__).parent.parent.resolve()
SKILL_SCRIPTS = ROOT / "skills" / "report-unknown-patterns" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import report_patterns  # noqa: E402


FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILURES.append(name)


# --------------------------------------------------------------------------- #
# Bug 4: parser must not drop rows containing escaped pipes in Sample M
# --------------------------------------------------------------------------- #


def test_parse_backlog_handles_escaped_pipes() -> None:
    backlog = (
        "# Conversion Backlog\n\n"
        "| Pattern | Files Affected | Occurrences | Sample M | First Seen | Status |\n"
        "|---|---|---|---|---|---|\n"
        "| Text.Combine | q1.pq | 1 | `Text.Combine(Names, \" \\| \")` | 2026-05-25 | Backlog |\n"
        "| List.Count | q2.pq | 2 | `List.Count(Items)` | 2026-05-25 | Backlog |\n"
    )
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8") as f:
        f.write(backlog)
        tmp_path = Path(f.name)
    try:
        rows = report_patterns.parse_backlog(tmp_path)
        _check(
            "parse_backlog returns BOTH rows when one contains escaped pipe",
            len(rows) == 2,
            detail=f"got {len(rows)} rows, expected 2: {[r.get('pattern') for r in rows]}",
        )
        text_combine = next((r for r in rows if r["pattern"] == "Text.Combine"), None)
        _check(
            "Text.Combine row is parsed (not dropped by pipe split)",
            text_combine is not None,
            detail=f"rows={[r.get('pattern') for r in rows]}",
        )
        if text_combine is not None:
            _check(
                "Text.Combine sample_m preserves the literal pipe",
                "|" in text_combine["sample_m"],
                detail=f"sample_m={text_combine['sample_m']!r}",
            )
            _check(
                "Text.Combine status column is correct (not mangled by cell misalignment)",
                text_combine["status"] == "Backlog",
                detail=f"status={text_combine['status']!r} — pipe split misaligned the cells",
            )
            _check(
                "Text.Combine first_seen column is a date (not mangled)",
                text_combine["first_seen"] == "2026-05-25",
                detail=f"first_seen={text_combine['first_seen']!r}",
            )
    finally:
        tmp_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Bug 2: plugin.json fallback must reach the plugin root, not skills/
# --------------------------------------------------------------------------- #


def test_get_repo_from_manifest_without_env_var() -> None:
    saved = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
    try:
        repo = report_patterns.get_repo_from_manifest()
        _check(
            "get_repo_from_manifest finds repo without CLAUDE_PLUGIN_ROOT (fallback works)",
            repo is not None,
            detail="returned None — fallback path is wrong (probably parent.parent.parent vs .parent.parent.parent.parent)",
        )
        if repo is not None:
            _check(
                "Returned repo string matches owner/name shape",
                "/" in repo and len(repo.split("/")) == 2,
                detail=f"got {repo!r}",
            )
    finally:
        if saved is not None:
            os.environ["CLAUDE_PLUGIN_ROOT"] = saved


def test_get_repo_from_manifest_with_env_var() -> None:
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    try:
        repo = report_patterns.get_repo_from_manifest()
        _check(
            "get_repo_from_manifest reads CLAUDE_PLUGIN_ROOT when set",
            repo is not None,
            detail="returned None even though env var pointed at plugin root",
        )
    finally:
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)


# --------------------------------------------------------------------------- #
# Bug 1: skill filter should be tolerant — accept 'Backlog' AND 'open'
# --------------------------------------------------------------------------- #


def test_status_filter_accepts_both_sentinels() -> None:
    backlog = (
        "# Conversion Backlog\n\n"
        "| Pattern | Files Affected | Occurrences | Sample M | First Seen | Status |\n"
        "|---|---|---|---|---|---|\n"
        "| A.Func | q1.pq | 1 | `A.Func()` | 2026-05-25 | Backlog |\n"
        "| B.Func | q2.pq | 1 | `B.Func()` | 2026-05-25 | open |\n"
        "| C.Func | q3.pq | 1 | `C.Func()` | 2026-05-25 | Reported (#42) |\n"
    )
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8") as f:
        f.write(backlog)
        tmp_path = Path(f.name)
    try:
        rows = report_patterns.parse_backlog(tmp_path)
        # Same filter logic as main(): tolerant to both 'backlog' and 'open'
        unreported = [
            r for r in rows if r["status"].lower() in ("backlog", "open")
        ]
        _check(
            "Filter picks up both 'Backlog' and 'open' rows, skips 'Reported (#42)'",
            len(unreported) == 2 and {r["pattern"] for r in unreported} == {"A.Func", "B.Func"},
            detail=f"got {[r.get('pattern') for r in unreported]}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def main() -> int:
    test_parse_backlog_handles_escaped_pipes()
    test_get_repo_from_manifest_without_env_var()
    test_get_repo_from_manifest_with_env_var()
    test_status_filter_accepts_both_sentinels()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s): {', '.join(FAILURES)}")
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
