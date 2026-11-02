"""The GPL-2.0 text must ship with every release.

`ops/fleet_release.py` deploys a release as a Git worktree of one commit, so a file
reaches every deployed plugin exactly when it is tracked at that commit.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_copying_is_tracked_and_is_gpl_2():
    subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "COPYING"], check=True, capture_output=True)
    text = (ROOT / "COPYING").read_text(encoding="utf-8")
    assert text.lstrip().startswith("GNU GENERAL PUBLIC LICENSE\n                       Version 2, June 1991")
