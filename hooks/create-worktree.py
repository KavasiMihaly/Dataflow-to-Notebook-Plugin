"""WorktreeCreate hook — creates a git worktree for agent isolation.
Auto-initializes git if the repo isn't a git repository yet.
Prints the absolute worktree path to stdout (required by Claude Code).
"""

import json
import os
import subprocess
import sys
import uuid


def run_git(args, cwd):
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result


def resolve_base_branch(cwd: str, requested: str) -> str:
    """Determine which branch (or commit-ish) to base the worktree on.

    Order of preference:
      1. `git rev-parse --abbrev-ref HEAD` — current branch. Works on all
         modern git versions, returns 'HEAD' if detached.
      2. `git branch --show-current` — backup for the 'HEAD' case (both are
         available in git >= 2.22). If the first method returned 'HEAD', this
         one returns '' and we move on.
      3. Enumerate local branches and prefer 'main' > 'master' > first branch.
      4. Fall back to the requested value only if nothing else worked. This
         should never happen in practice because the hook's own init step
         creates at least one commit (and therefore at least one branch).

    Never silently default to 'main' when the repo is on 'master' — that was
    the original bug (I-041).
    """
    # 1) abbrev-ref HEAD
    r = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if r.returncode == 0:
        name = r.stdout.strip()
        if name and name != "HEAD":
            return name

    # 2) --show-current
    r = run_git(["branch", "--show-current"], cwd)
    if r.returncode == 0:
        name = r.stdout.strip()
        if name:
            return name

    # 3) enumerate branches; prefer common defaults
    r = run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads/"], cwd)
    if r.returncode == 0:
        branches = [line.strip() for line in r.stdout.splitlines() if line.strip()]
        for preferred in ("main", "master"):
            if preferred in branches:
                return preferred
        if branches:
            return branches[0]

    # 4) last resort — the requested/default value
    return requested


def main():
    data = json.load(sys.stdin)
    # Generate a unique worktree ID if none provided — prevents collisions
    # when multiple agents spawn worktrees in parallel
    worktree_id = data.get("worktree_id") or f"wt-{uuid.uuid4().hex[:8]}"
    cwd = data.get("cwd", os.getcwd())
    requested_base = data.get("base_branch", "main")

    # Auto-init git if not a repo
    check = run_git(["rev-parse", "--git-dir"], cwd)
    if check.returncode != 0:
        run_git(["init"], cwd)
        run_git(["add", "-A"], cwd)
        run_git(["commit", "-m", "Initial scaffold for worktree support", "--allow-empty"], cwd)

    # Ensure we have at least one commit (bare init edge case)
    log = run_git(["log", "--oneline", "-1"], cwd)
    if log.returncode != 0:
        run_git(["add", "-A"], cwd)
        run_git(["commit", "-m", "Initial scaffold for worktree support", "--allow-empty"], cwd)

    # Robustly resolve the base branch — handles master-vs-main automatically
    base_branch = resolve_base_branch(cwd, requested_base)

    # Create worktree path
    worktree_path = os.path.join(cwd, ".claude", "worktrees", worktree_id)
    os.makedirs(os.path.dirname(worktree_path), exist_ok=True)

    # Create the worktree (detached so we don't need a new branch)
    result = run_git(["worktree", "add", "--detach", worktree_path, base_branch], cwd)
    if result.returncode != 0:
        print(
            f"Error creating worktree: {result.stderr.strip()}\n"
            f"Attempted base branch: {base_branch!r}. "
            f"If this is wrong, set `base_branch` in the WorktreeCreate event "
            f"data, or normalize the repo to branch 'main' via "
            f"`git branch -m main` after `git init`.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Print absolute path to stdout (required)
    print(os.path.abspath(worktree_path))


if __name__ == "__main__":
    main()
