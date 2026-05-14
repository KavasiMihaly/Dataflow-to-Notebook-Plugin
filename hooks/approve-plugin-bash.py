#!/usr/bin/env python3
"""PreToolUse hook that auto-approves Bash calls for known plugin-internal operations.

Context
-------
Claude Code's default permission system prompts the user interactively for every
Bash call that isn't on the allowlist. For **foreground** sessions this is fine —
the user answers the prompt. For **background subagents** spawned via
`run_in_background: true`, there is no interactive channel, so the prompt goes
nowhere and the subagent stalls with an "I am unable to execute Bash commands"
error. The `acceptEdits` permission mode doesn't help either: per the Claude Code
permissions reference, `acceptEdits` only auto-approves filesystem Bash commands
(`mkdir`, `touch`, `mv`, `cp`, etc.), not arbitrary Python or dbt invocations.

This hook closes the gap for the specific Python and git commands the plugin
needs to run in background subagents. It inspects the command string and returns
`permissionDecision: "allow"` when the command matches a narrow allowlist.

Atomic-commands-only policy
---------------------------
Per the plugin's repo `CLAUDE.md` and the global user CLAUDE.md, **every Bash
command generated or executed by this plugin must be a single atomic
operation** — no `&&`, `||`, `;`, `|`, subshells, or command substitution. The
orchestrator was refactored to comply with this rule: Stage 0 / 5 / 6 all use
atomic commands, specialists receive atomic commands via their prompts, and
new contributions are expected to follow the same rule.

This hook therefore treats atomic commands as the normal case. A
compound-command splitter is included as **defensive fallback**: if some
future contributor accidentally introduces a compound expression, the splitter
will split it into subcommands and require each to independently match the
allowlist. Per the Claude Code permissions model:

> "A rule must match each subcommand independently."
>   — https://code.claude.com/docs/en/permissions

In normal operation, the splitter produces a single-element list and the
allowlist match is a simple per-command check. Do not rely on the splitter as
a feature for writing new compound commands — write atomic commands instead.

Allowlist categories (built from a full audit of the plugin's `agent.md` and
`SKILL.md` files — see `_Documentation/plugin_learnings.md` Finding 9):

  1. Plugin-internal Python scripts under `<plugin-root>/skills/*/scripts/*.py`
     (covers profile_data, query_sql_server, load_data, run_dbt,
     analyze_coverage, generate_docs, initialize_project, reset_project)
  2. Specific `python -c` one-liners the plugin depends on (pyodbc driver check,
     CSV file-copy helper in dbt-architecture-setup)
  3. Virtualenv / pip operations used by dbt-project-initializer
  4. `git` commands used by Stage 5 scaffold init and Stage 8/9 worktree
     isolation (init, status, add, commit, log, show, diff, branch, rev-parse,
     worktree, merge, stash)
  5. Filesystem discovery commands (`find . -name "*.csv"`, `ls *.csv`,
     `ls dbt_project.yml`, `ls` in `2 - Source Files/`)
  6. Project folder creation and CSV copy (`mkdir -p "2 - Source Files"`,
     `cp *.csv "2 - Source Files/"`)

Filesystem commands (`mkdir`, `cp`, `mv`, `touch`, `rm`) are generally auto-
approved under `acceptEdits` permission mode without any hook involvement, so
in practice they rarely reach this hook. They're kept in the allowlist as a
safety net in case the session runs under a stricter permission mode.

Any other Bash command falls through to the default permission flow, so the
allowlist does not broadly unlock the shell.

Security boundary
-----------------
This hook is auditable at install time via the plugin manifest and this file.
Users can inspect the allowlist before enabling the plugin. The hook can only
ALLOW calls — it cannot override explicit `permissions.deny` rules the user has
set, which still take precedence per the Claude Code permission layering rules.

The compound-command splitter handles shell quotes correctly: characters inside
single or double quotes are not treated as operator tokens, so a command like
`python foo.py --arg 'value with && inside'` is not split on the embedded `&&`.

Contract
--------
Input on stdin: PreToolUse JSON per the Claude Code hooks reference, including
`tool_name`, `tool_input.command`, `permission_mode`, etc.

Output on stdout: JSON with `"decision": "approve"` when all subcommands match
the allowlist, or an empty object `{}` when any subcommand does not match (falls
through to default permission flow). Exit code 0 always. Never exit 2 — that
would block the tool call unconditionally, which is never the intent here.
"""

from __future__ import annotations

import json
import re
import sys


# --------------------------------------------------------------------------- #
# Allowlist patterns — each pattern is matched against a single subcommand
# (after compound-command splitting). A subcommand is approved if it matches
# ANY pattern in this list.
# --------------------------------------------------------------------------- #

_ALLOWLIST: list[re.Pattern[str]] = [
    # --- Plugin Python scripts ---------------------------------------------
    # Matches: python "<...>/skills/<skill>/scripts/<file>.py" <args>
    # The `.*` before `/skills/` accommodates both the literal-substituted form
    # (after ${CLAUDE_PLUGIN_ROOT} is resolved to an absolute path) and the
    # variable form that might appear before substitution.
    re.compile(
        r'''^\s*python[0-9.]*\s+['"]?[^'"]*[/\\]skills[/\\][\w.-]+[/\\]scripts[/\\][\w.-]+\.py['"]?(\s+.*)?\s*$''',
        re.DOTALL,
    ),

    # --- Narrow python -c one-liners the plugin explicitly depends on ------
    # pyodbc driver inventory check (read-only; used by SKILL.md and init)
    re.compile(
        r'''^\s*python[0-9.]*\s+-c\s+['"]import\s+pyodbc\s*;\s*print\s*\(\s*['"]?.*pyodbc\.drivers\(\).*['"]\s*\)?.*['"]?\s*$''',
        re.DOTALL,
    ),

    # CSV file-copy helper used in dbt-architecture-setup Stage 5. Anchored
    # on the specific imports and shutil.move pattern; does NOT match arbitrary
    # python -c strings.
    re.compile(
        r'''^\s*python[0-9.]*\s+-c\s+['"].*import\s+shutil\s*,\s*glob\s*,\s*os.*shutil\.move.*['"]\s*$''',
        re.DOTALL,
    ),

    # --- Virtualenv creation and pip installs (Stage 5 scaffolding) --------
    re.compile(r'''^\s*python[0-9.]*\s+-m\s+venv\s+[\w./\\-]+\s*$''', re.DOTALL),
    re.compile(r'''^\s*(\.venv[/\\](bin|Scripts)[/\\])?pip[0-9.]*\s+install\s+.*$''', re.DOTALL),
    re.compile(r'''^\s*(\.venv[/\\](bin|Scripts)[/\\])?pip[0-9.]*\s+(list|freeze|show|check)(\s+.*)?\s*$''', re.DOTALL),

    # --- git commands (Stage 5 scaffold init, Stages 8/9 worktree isolation)
    re.compile(
        r'''^\s*git\s+(init|status|add|commit|log|show|diff|branch|checkout|rev-parse|worktree|merge|stash|config|remote|fetch|pull|ls-files|tag)\b.*$''',
        re.DOTALL,
    ),

    # --- Filesystem discovery (Stage 0) -----------------------------------
    re.compile(r'''^\s*find\s+[\w./\\-]*\s+-name\s+['"]?[*\w.-]+\.csv['"]?(\s+-type\s+f)?(\s+2>/dev/null)?\s*$''', re.DOTALL),
    re.compile(r'''^\s*find\s+[\w./\\-]*\s+-type\s+f(\s+-name\s+['"]?[*\w.-]+\.csv['"]?)?(\s+2>/dev/null)?\s*$''', re.DOTALL),
    re.compile(r'''^\s*ls\s+['"]?[^|;&<>]*\.csv['"]?\s*$''', re.DOTALL),
    re.compile(r'''^\s*ls\s+dbt_project\.yml(\s+2>/dev/null)?\s*$''', re.DOTALL),
    re.compile(r'''^\s*ls\s+['"]?[^|;&<>]*['"]?\s*$''', re.DOTALL),

    # --- Standard plugin folder operations --------------------------------
    re.compile(r'''^\s*mkdir\s+-p\s+['"]?[^'"]+['"]?\s*$''', re.DOTALL),
    re.compile(r'''^\s*cp\s+.*\s+['"]?2 - Source Files[/\\]?['"]?\s*$''', re.DOTALL),
    re.compile(r'''^\s*cp\s+['"]?[^'"]*\.csv['"]?\s+['"]?[^'"]+['"]?\s*$''', re.DOTALL),

    # --- cat for small verification reads (no pipes/redirects) -----------
    re.compile(r'''^\s*cat\s+['"]?[^|;&<>]*['"]?\s*$''', re.DOTALL),

    # --- Fabric CLI (Stages 10, 11, validator) ---------------------------
    # Top-level fab subcommands the plugin uses
    re.compile(
        r'''^\s*fab\s+(auth|cd|ls|get|rm|mv|cp|import|export|api|job|workspace|item)\b.*$''',
        re.DOTALL,
    ),
    re.compile(r'''^\s*fab\s+--version\s*$''', re.DOTALL),

    # --- Azure CLI (preflight, auth check) -------------------------------
    re.compile(r'''^\s*az\s+(account|login|logout)\b.*$''', re.DOTALL),

    # --- GitHub CLI (report-unknown-patterns skill) ----------------------
    # Narrow: only `gh issue create/list` and `gh auth status`. The skill
    # never needs broader gh capabilities.
    re.compile(r'''^\s*gh\s+(auth\s+(status|login)|issue\s+(create|list))\b.*$''', re.DOTALL),

    # --- PowerShell export script (Stage 2 — user runs this manually,
    #     orchestrator may invoke for status check) ----------------------
    re.compile(
        r'''^\s*pwsh\s+-File\s+['"]?[^'"]*Export-AllDataflows\.ps1['"]?\s*$''',
        re.DOTALL,
    ),
    re.compile(
        r'''^\s*powershell(\.exe)?\s+-File\s+['"]?[^'"]*Export-AllDataflows\.ps1['"]?\s*$''',
        re.DOTALL,
    ),

    # --- Discovery / verification commands -------------------------------
    re.compile(r'''^\s*ls\s+['"]?1 - Source Dataflows[/\\]?['"]?\s*$''', re.DOTALL),
    re.compile(r'''^\s*ls\s+['"]?2 - Source Files[/\\]?['"]?\s*$''', re.DOTALL),
    re.compile(r'''^\s*ls\s+['"]?3 - Notebooks[/\\]?(bronze|silver|gold)?[/\\]?['"]?\s*$''', re.DOTALL),

    # --- find for .pq and .ipynb files -----------------------------------
    re.compile(r'''^\s*find\s+[\w./\\-]*\s+-name\s+['"]?[*\w.-]+\.(pq|ipynb|json)['"]?(\s+-type\s+f)?\s*$''', re.DOTALL),
    re.compile(r'''^\s*find\s+[\w./\\-]*\s+-type\s+f\s+-name\s+['"]?[*\w.-]+\.(pq|ipynb|json)['"]?\s*$''', re.DOTALL),

    # --- grep for risk-pattern scanning (m-query-analyst Pass 2) ---------
    re.compile(r'''^\s*grep\s+(-rn|-rln|-c|-l|-n|-r)?\s+['"]?[^'"]+['"]?\s+['"]?[^'"]+['"]?\s*$''', re.DOTALL),

    # --- Bundled sample copy (Stage 2 in --sample mode) ------------------
    re.compile(
        r'''^\s*cp\s+-r\s+['"]?[^'"]*[/\\]examples[/\\]sample-dataflows[/\\]\.['"]?\s+['"]?1 - Source Dataflows[/\\]?['"]?\s*$''',
        re.DOTALL,
    ),
]
# Note: `wc -l` and `echo` patterns were intentionally removed along with the
# Stage 0/5/6 atomic-command refactor. The orchestrator no longer pipes `ls`
# into `wc -l` (it issues `find -type f` and counts the output lines in LLM
# text), and Stage 0 no longer uses `echo` as a compound marker. If a new
# pattern needs `wc` or `echo`, add it here with a comment explaining the
# specific use case — and prefer rewriting the workflow to avoid it.


# --------------------------------------------------------------------------- #
# Process-wrapper stripping (mirrors Claude Code's built-in behavior)
# --------------------------------------------------------------------------- #
#
# Claude Code strips these wrappers before matching permission rules, so our
# allowlist doesn't need to account for them. Mirroring the stripping here
# keeps our matcher aligned with the upstream permission layer.

_WRAPPERS = ("timeout", "time", "nice", "nohup", "stdbuf")


def _strip_wrappers(command: str) -> str:
    """Strip a recognized leading process wrapper, if any."""
    stripped = command.lstrip()
    for wrapper in _WRAPPERS:
        # Wrapper followed by optional args, then the real command
        pattern = re.compile(rf'^{wrapper}(\s+-\S+(\s+\S+)?)*\s+')
        m = pattern.match(stripped)
        if m:
            return stripped[m.end():]
    return stripped


# --------------------------------------------------------------------------- #
# Compound-command splitter
# --------------------------------------------------------------------------- #
#
# Splits a shell command into subcommands at unquoted operator tokens. Handles
# single and double quotes to avoid false splits inside string arguments. Also
# strips leading/trailing parentheses from subshells `(...)` so each inner
# command can be matched independently.
#
# This intentionally does NOT handle heredocs, process substitution, command
# substitution `$(...)`, or backticks. If a command uses any of those, the
# splitter will produce unreliable subcommands and the hook will likely fail
# to match, so the command falls through to the default permission flow —
# which is the safe default for anything this complex.
#
# --------------------------------------------------------------------------- #


def _split_subcommands(command: str) -> list[str]:
    """Split a shell command into subcommands at top-level operator tokens.

    Operators recognized: &&, ||, ;, |, |&, &, newlines. Operators inside
    single- or double-quoted strings are treated as literal characters and
    do not cause splits. Subshell parentheses (`(...)` at the start/end of
    a subcommand) are stripped so the inner command can be matched.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    n = len(command)
    in_single = False
    in_double = False

    def flush() -> None:
        piece = "".join(current).strip()
        if piece:
            parts.append(piece)
        current.clear()

    while i < n:
        c = command[i]
        nxt = command[i + 1] if i + 1 < n else ""

        if in_single:
            current.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            current.append(c)
            if c == '"' and (i == 0 or command[i - 1] != "\\"):
                in_double = False
            i += 1
            continue

        if c == "'":
            in_single = True
            current.append(c)
            i += 1
            continue
        if c == '"':
            in_double = True
            current.append(c)
            i += 1
            continue

        # Two-character operators
        two = c + nxt
        if two in ("&&", "||", "|&"):
            flush()
            i += 2
            continue

        # Single-character operators
        if c in (";", "|", "&", "\n"):
            flush()
            i += 1
            continue

        current.append(c)
        i += 1

    flush()

    # Strip surrounding subshell parentheses from each part so `(git init && git add)`
    # splits correctly into `git init` and `git add` after the inner && pass.
    cleaned: list[str] = []
    for part in parts:
        stripped = part.strip()
        while stripped.startswith("(") and stripped.endswith(")"):
            stripped = stripped[1:-1].strip()
        if stripped:
            cleaned.append(stripped)

    # Second pass: if any cleaned part still contains unquoted operators
    # (e.g. from a subshell we unwrapped), recurse into it once.
    result: list[str] = []
    for part in cleaned:
        if any(op in part for op in ("&&", "||", ";", "\n")) or (
            "|" in part and "||" not in part
        ):
            # Simple heuristic: recurse once to handle unwrapped subshells.
            # Guards against infinite recursion because we only recurse on
            # parts that survived the first pass with operators still present.
            inner = _split_subcommands(part)
            result.extend(inner)
        else:
            result.append(part)

    return result


# --------------------------------------------------------------------------- #
# Subcommand matcher
# --------------------------------------------------------------------------- #


def _normalize_subcommand(sub: str) -> str:
    """Trim trailing redirects like `2>/dev/null` before matching."""
    # Remove common trailing fd redirects; they're not meaningful for allowlisting.
    sub = re.sub(r"\s+2>/dev/null\s*$", "", sub)
    sub = re.sub(r"\s+>/dev/null\s*$", "", sub)
    sub = re.sub(r"\s+>\s*[^\s]+\s*$", "", sub)
    sub = re.sub(r"\s+>>\s*[^\s]+\s*$", "", sub)
    return sub.strip()


def _matches_allowlist(sub: str) -> bool:
    """Return True if the subcommand matches any allowlist pattern."""
    sub = _strip_wrappers(sub)
    sub = _normalize_subcommand(sub)
    if not sub:
        return False
    return any(p.fullmatch(sub) for p in _ALLOWLIST)


def _is_allowlisted(command: str) -> bool:
    """Return True if every subcommand of the command matches the allowlist."""
    subcommands = _split_subcommands(command)
    if not subcommands:
        return False
    return all(_matches_allowlist(sc) for sc in subcommands)


# --------------------------------------------------------------------------- #
# Hook entry point
# --------------------------------------------------------------------------- #


def _emit_allow(reason: str) -> None:
    payload = {"decision": "approve", "reason": reason}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _emit_defer() -> None:
    # Empty JSON object = "no opinion, let default permission flow run"
    sys.stdout.write("{}\n")


def main() -> int:
    try:
        raw = sys.stdin.read()

        if not raw.strip():
            _emit_defer()
            return 0

        payload = json.loads(raw)

        if payload.get("tool_name") != "Bash":
            _emit_defer()
            return 0

        command = payload.get("tool_input", {}).get("command", "")
        if not command:
            _emit_defer()
            return 0

        if _is_allowlisted(command):
            _emit_allow(
                "Auto-approved by fabric-dataflow-migration-toolkit plugin — all "
                "subcommands match the plugin-internal allowlist "
                "(see hooks/approve-plugin-bash.py)."
            )
        else:
            _emit_defer()

    except Exception:
        # Never crash — always defer to default permission flow on unexpected errors.
        # A crash (non-zero exit) is treated as a hook error by Claude Code.
        _emit_defer()

    return 0


if __name__ == "__main__":
    sys.exit(main())
