#!/usr/bin/env python3
"""
Report Unknown Patterns

Reads _Documentation/conversion-backlog.md, sanitizes M snippets, creates
GitHub issues against the plugin repo so unknown patterns can be added to
the risk catalog in future releases.

Opt-in only — invoked by the orchestrator when migration-design.md Section 5
recorded `Report patterns: yes`, OR run manually with --dry-run for preview.

Usage:
  python report_patterns.py --dry-run
  python report_patterns.py --auto-approve
  python report_patterns.py --pattern "Web.Contents"
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Sanitization rules
# --------------------------------------------------------------------------- #
# Each rule is (regex, replacement). Order matters — earlier rules see
# unredacted text. The strategy is layered:
#   1. Specific PII (URLs, GUIDs, SQL conn args, file paths, sheet names) first
#   2. Column references and quoted identifiers next
#   3. Catchall for remaining string/numeric literals last (skips already-
#      redacted placeholders so we don't double-redact)
# The reader of a GitHub issue needs to understand the M function's call
# shape and structure — they do NOT need column names, filter values, or
# specific data points.

SANITIZE_RULES = [
    # --- Layer 1: specific PII ----------------------------------------------
    # Storage URLs (most specific first)
    (r"https://[\w-]+\.blob\.core\.windows\.net/[\w-]+/", "<REDACTED_URL>/<REDACTED_CONTAINER>/"),
    (r"https://[\w-]+\.dfs\.core\.windows\.net/[\w-]+/", "<REDACTED_URL>/<REDACTED_CONTAINER>/"),
    (r"https://[\w-]+\.blob\.core\.windows\.net/", "<REDACTED_URL>/"),
    (r"https://[\w-]+\.dfs\.core\.windows\.net/", "<REDACTED_URL>/"),
    (r"abfss://[\w-]+@[\w-]+\.dfs\.core\.windows\.net/", "abfss://<REDACTED_CONTAINER>@<REDACTED_ACCOUNT>.dfs.core.windows.net/"),
    (r"wasbs://[\w-]+@[\w-]+\.blob\.core\.windows\.net/", "wasbs://<REDACTED_CONTAINER>@<REDACTED_ACCOUNT>.blob.core.windows.net/"),
    # Web/API URLs (broader)
    (r'https?://[a-zA-Z0-9.-]+(/[^"\s]*)?', "<REDACTED_URL>"),
    # SQL connections
    (r'Sql\.Database\("[^"]*"\s*,\s*"[^"]*"\)', 'Sql.Database("<REDACTED_SERVER>", "<REDACTED_DB>")'),
    (r'Sql\.Databases\("[^"]*"\)', 'Sql.Databases("<REDACTED_SERVER>")'),
    # GUIDs
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "<REDACTED_GUID>"),
    # File paths in quotes
    (r'"[^"]*\.(csv|xlsx|xls|json|parquet|tsv|txt)"', '"<REDACTED_PATH>"'),
    # Excel sheet name (positional in record literal)
    (r'Item\s*=\s*"[^"]*"', 'Item = "<REDACTED_SHEET>"'),

    # --- Layer 2: column references and quoted identifiers ------------------
    # Column refs `[Column Name]` — bracketed identifier with no `=` inside
    # (record literals like `[Name = "X"]` contain `=` and are excluded).
    # Pattern: open bracket, then chars that are NOT `[`, `]`, or `=`, then close.
    # The `[^\[\]=]+` ensures we only match true column refs, not record literals.
    (r"\[([^\[\]=]+)\]", "[<REDACTED_COL>]"),

    # Quoted identifiers `#"Identifier"` — used as both step names AND column
    # names with spaces. Both leak business intent; redact uniformly.
    (r'#"[^"]+"', '#"<REDACTED_IDENT>"'),

    # --- Layer 4: numeric literals in filter contexts -----------------------
    # M small numbers (0-99) are typically structural (Table.Skip(_, 4),
    # column index {0}, etc.). Larger numbers are usually thresholds or IDs
    # that may carry signal — redact those.
    (r"\b(\d{3,})\b", "<REDACTED_NUMBER>"),
]


def _redact_remaining_strings(text: str) -> str:
    """Tokenize into string-literal vs non-string spans, then redact string
    bodies that haven't already been replaced by a Layer 1/2 rule.

    This is more robust than a regex catchall because regex cannot
    distinguish a closing `"` from a subsequent opening `"`. Walking the
    text character-by-character with a tiny state machine pairs quotes
    correctly even when adjacent string args appear like `"a", "b"`.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            # Find matching close quote (no escape handling — M does not
            # support backslash escapes, only `""` for embedded quotes).
            j = i + 1
            while j < n and text[j] != '"':
                j += 1
            if j >= n:
                # Unterminated string — emit rest verbatim and stop.
                out.append(text[i:])
                break
            body = text[i + 1 : j]
            # Preserve strings that:
            #   - already contain a Layer 1/2 placeholder
            #   - have no word chars (likely M syntax: ",", "\n", etc.)
            if "<REDACTED_" in body or not re.search(r"\w", body):
                out.append(text[i : j + 1])
            else:
                out.append('"<REDACTED_VALUE>"')
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def sanitize_snippet(snippet: str) -> str:
    """Apply all sanitization rules in order, plus the string-token pass."""
    out = snippet
    for pattern, replacement in SANITIZE_RULES:
        out = re.sub(pattern, replacement, out)
    # Layer 3 (string catchall) runs as a token-aware pass AFTER all regex
    # rules so that quote pairing is honored.
    out = _redact_remaining_strings(out)
    return out


# --------------------------------------------------------------------------- #
# Backlog parsing
# --------------------------------------------------------------------------- #


# Placeholder used to round-trip escaped pipes (`\|`) through `split("|")`.
# Markdown tables require pipes inside cells to be escaped, but the naive
# splitter doesn't know that — without this we mis-split rows whose Sample M
# cell contains a pipe literal (e.g. `Text.Combine(Names, " \| ")`).
_ESCAPED_PIPE_SENTINEL = "\x00PIPE\x00"


def parse_backlog(path: Path) -> list[dict]:
    """Parse the backlog markdown table. Returns list of pattern dicts."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and not stripped.startswith("|---") and not stripped.startswith("| Pattern"):
            # Protect escaped pipes before splitting on the structural `|`,
            # then restore them inside each cell.
            protected = stripped.replace(r"\|", _ESCAPED_PIPE_SENTINEL)
            cells = [c.strip().replace(_ESCAPED_PIPE_SENTINEL, "|") for c in protected.strip("|").split("|")]
            if len(cells) >= 6:
                rows.append({
                    "pattern": cells[0],
                    "files_affected": cells[1],
                    "occurrences": cells[2],
                    "sample_m": cells[3],
                    "first_seen": cells[4],
                    "status": cells[5],
                })
    return rows


def update_backlog_status(path: Path, pattern: str, new_status: str) -> bool:
    """Update the Status column for a given pattern row. Returns True if updated."""
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    updated = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and pattern in stripped:
            protected = stripped.replace(r"\|", _ESCAPED_PIPE_SENTINEL)
            cells = [c.strip().replace(_ESCAPED_PIPE_SENTINEL, "|") for c in protected.strip("|").split("|")]
            if len(cells) >= 6 and cells[0] == pattern:
                cells[5] = new_status
                # Re-escape any literal pipes inside cells when writing back.
                lines[i] = "| " + " | ".join(c.replace("|", r"\|") for c in cells) + " |"
                updated = True
                break
    if updated:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated


# --------------------------------------------------------------------------- #
# GitHub issue creation
# --------------------------------------------------------------------------- #


def get_repo_from_manifest() -> str | None:
    """Read repository URL from plugin.json.

    Resolution order:
      1. ``$CLAUDE_PLUGIN_ROOT`` (set by Claude Code when the skill is invoked
         from a plugin context)
      2. Walk up from this script's location until a ``.claude-plugin`` dir is
         found. The script lives at
         ``<plugin-root>/skills/report-unknown-patterns/scripts/report_patterns.py``,
         so the manifest is exactly four levels up — but walking is more robust
         to future re-org than a hard-coded `parent.parent.parent.parent`.
    """
    plugin_root: str | None = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        here = Path(__file__).resolve()
        for ancestor in here.parents:
            if (ancestor / ".claude-plugin" / "plugin.json").exists():
                plugin_root = str(ancestor)
                break
    if not plugin_root:
        return None
    manifest = Path(plugin_root) / ".claude-plugin" / "plugin.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        repo_url = data.get("repository", "")
        # Convert https://github.com/owner/repo[.git] to owner/repo
        m = re.match(r"https?://github\.com/([\w-]+)/([\w.-]+?)(\.git)?/?$", repo_url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    except Exception:
        return None
    return None


# Default colors for auto-created labels. Issue body text is informational
# only; pick muted colors so the labels don't dominate the issue list.
_LABEL_DEFAULTS: dict[str, dict[str, str]] = {
    "conversion-pattern": {"color": "1d76db", "description": "M pattern needing PySpark conversion"},
    "community-submitted": {"color": "0e8a16", "description": "Filed by the report-unknown-patterns skill"},
}


def ensure_labels_exist(repo: str, labels: list[str]) -> list[str]:
    """Create any of `labels` that don't yet exist on `repo`.

    Returns the list of labels that were newly created (empty if all existed
    or if probing failed). Errors are intentionally swallowed — label creation
    is best-effort; if it fails, `gh issue create` will surface a clear error.
    """
    if not labels:
        return []
    try:
        probe = subprocess.run(
            ["gh", "label", "list", "--repo", repo, "--limit", "200", "--json", "name"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return []
    if probe.returncode != 0:
        return []
    try:
        existing = {entry["name"] for entry in json.loads(probe.stdout or "[]")}
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    created: list[str] = []
    for label in labels:
        if label in existing:
            continue
        defaults = _LABEL_DEFAULTS.get(label, {"color": "ededed", "description": ""})
        try:
            r = subprocess.run(
                [
                    "gh", "label", "create", label,
                    "--repo", repo,
                    "--color", defaults["color"],
                    "--description", defaults["description"],
                ],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                created.append(label)
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            continue
    return created


def gh_create_issue(repo: str, title: str, body: str, labels: list[str]) -> tuple[str | None, str]:
    """Create a GitHub issue via gh CLI. Returns (issue_url_or_None, error_or_empty)."""
    # Auto-create labels first so first-install runs don't fail per-pattern
    # with `'conversion-pattern' not found`.
    ensure_labels_exist(repo, labels)
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return r.stdout.strip(), ""
        return None, (r.stderr or r.stdout or "unknown gh error").strip()
    except FileNotFoundError:
        return None, "gh CLI not found on PATH; run: install GitHub CLI from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return None, "gh issue create timed out"
    except Exception as e:
        return None, str(e)


def build_issue_body(pattern: dict, sanitized_snippet: str) -> str:
    return f"""## Pattern: {pattern['pattern']}

**Detected occurrences:** {pattern['occurrences']} across {pattern['files_affected']}
**First seen:** {pattern['first_seen']}

### Sanitized M snippet

```m
{sanitized_snippet}
```

### Plugin context

- Plugin: fabric-dataflow-migration-toolkit
- This issue was filed via the `report-unknown-patterns` skill with explicit user opt-in.
- Connection strings, GUIDs, file paths, and sheet names have been redacted automatically. No raw business data is included.

### Suggested next step (for plugin author)

If this is a known M pattern, add it to `reference/m-conversion-risk-catalog.md` with:
- A stable RISK-NN identifier
- Severity classification (Low / Medium / High)
- Best-effort PySpark mitigation

---
*Auto-filed by the `report-unknown-patterns` skill. See `_Documentation/conversion-backlog.md` in the plugin source.*
"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(description="Report unknown M patterns as GitHub issues.")
    parser.add_argument("--backlog", default="_Documentation/conversion-backlog.md")
    parser.add_argument("--pattern", default=None, help="Filter to one pattern (substring match)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating issues")
    parser.add_argument("--auto-approve", action="store_true", help="Skip per-pattern preview")
    parser.add_argument("--repo", default=None, help="Override target repo (owner/name)")
    parser.add_argument("--json", action="store_true", help="Output JSON envelope")
    args = parser.parse_args()

    backlog_path = Path(args.backlog)
    if not backlog_path.exists():
        msg = f"Backlog file not found: {backlog_path}"
        if args.json:
            print(json.dumps({"status": "skipped", "reason": msg}))
        else:
            print(msg)
        sys.exit(0)

    rows = parse_backlog(backlog_path)
    # Accept both 'Backlog' (the canonical sentinel) and 'open' — the latter
    # is what some LLM-driven runs of m-query-analyst have emitted in practice
    # when the orchestrator prompt didn't pin the value explicitly. See #15.
    backlog_rows = [r for r in rows if r["status"].lower() in ("backlog", "open")]

    if args.pattern:
        backlog_rows = [r for r in backlog_rows if args.pattern.lower() in r["pattern"].lower()]

    if not backlog_rows:
        envelope = {
            "status": "skipped",
            "reason": "No unknown patterns with status=Backlog to report",
            "scanned": len(rows),
        }
        if args.json:
            print(json.dumps(envelope, indent=2))
        else:
            print(envelope["reason"])
        sys.exit(0)

    repo = args.repo or get_repo_from_manifest()
    if not repo and not args.dry_run:
        msg = "Cannot determine target repo. Pass --repo owner/name or set repository in plugin.json"
        if args.json:
            print(json.dumps({"status": "failed", "error": msg}))
        else:
            print(f"ERROR: {msg}")
        sys.exit(2)

    reported = []
    skipped_by_user = []
    failed = []

    for row in backlog_rows:
        sanitized = sanitize_snippet(row["sample_m"])
        title = f"[Pattern] {row['pattern']} — convert to PySpark"
        body = build_issue_body(row, sanitized)

        if not args.auto_approve and not args.dry_run:
            print(f"\n=== Pattern: {row['pattern']} ===")
            print(f"Original snippet:\n  {row['sample_m'][:200]}")
            print(f"\nSanitized snippet:\n  {sanitized[:200]}")
            print(f"\nWill be filed at: github.com/{repo}/issues")
            answer = input("Post this issue? [y/N/skip-rest]: ").strip().lower()
            if answer == "skip-rest":
                break
            if answer != "y":
                skipped_by_user.append({"pattern": row["pattern"], "reason": "user declined preview"})
                continue

        if args.dry_run:
            print(f"[DRY-RUN] Would file: {title}")
            print(f"[DRY-RUN] Body preview:\n{body[:400]}\n")
            reported.append({"pattern": row["pattern"], "issue_url": "(dry-run)"})
            continue

        url, err = gh_create_issue(repo, title, body, ["conversion-pattern", "community-submitted"])
        if url:
            reported.append({"pattern": row["pattern"], "issue_url": url})
            # Extract issue number from URL for status update
            m = re.search(r"/issues/(\d+)$", url)
            issue_num = m.group(1) if m else "?"
            update_backlog_status(backlog_path, row["pattern"], f"Reported (#{issue_num})")
            if not args.json:
                print(f"FILED: {url}")
        else:
            failed.append({"pattern": row["pattern"], "error": err})
            if not args.json:
                print(f"FAILED ({row['pattern']}): {err}")

    status = "success" if not failed and reported else ("partial" if reported else "skipped")
    envelope = {
        "status": status,
        "mode": "dry-run" if args.dry_run else "live",
        "scanned": len(rows),
        "backlog_count": len(backlog_rows),
        "reported": reported,
        "skipped_by_user": skipped_by_user,
        "failed": failed,
    }

    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        print(f"\n=== Summary ===")
        print(f"Scanned: {envelope['scanned']}, Backlog: {envelope['backlog_count']}, "
              f"Reported: {len(reported)}, Skipped: {len(skipped_by_user)}, Failed: {len(failed)}")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
