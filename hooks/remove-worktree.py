"""WorktreeRemove hook — cleans up a git worktree after agent completes.
Fire-and-forget: always exits 0.
"""

import json
import os
import subprocess
import sys


def main():
    data = json.load(sys.stdin)
    worktree_path = data.get("worktree_path", "")

    if not worktree_path or not os.path.isdir(worktree_path):
        sys.exit(0)

    # Find the parent repo (walk up from worktree to find .claude/worktrees ancestor)
    parent_dir = worktree_path
    for _ in range(10):
        parent_dir = os.path.dirname(parent_dir)
        git_dir = os.path.join(parent_dir, ".git")
        if os.path.isdir(git_dir) or os.path.isfile(git_dir):
            break
    else:
        # Fallback: just delete the directory
        import shutil
        shutil.rmtree(worktree_path, ignore_errors=True)
        sys.exit(0)

    subprocess.run(
        ["git", "worktree", "remove", "--force", worktree_path],
        cwd=parent_dir,
        capture_output=True,
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
