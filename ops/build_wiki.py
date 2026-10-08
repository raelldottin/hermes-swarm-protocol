#!/usr/bin/env python3
"""Compile or check a local Swarm Wiki; never change canonical stores."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hermes_swarm_protocol"))
import wiki_compiler as wiki


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path)
    parser.add_argument("--tree", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--maintainer", action="append", default=[])
    parser.add_argument("--task-workspace-root", type=Path, action="append", default=[],
                        help="Additional authorized task workspace root; repeat for multiple roots")
    parser.add_argument("--hermes-source", type=Path, default=Path.home() / ".hermes/hermes-agent")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--lint", action="store_true")
    args = parser.parse_args(argv)
    try:
        for value in (args.board, args.project):
            if not value or Path(value).name != value or value in {".", ".."} or "\\" in value:
                raise ValueError("board/project must be a single path-safe name")
        root = Path.home() / ".hermes"  # Intentionally ignores worker HERMES_HOME.
        db = args.db or root / "kanban/boards" / args.board / "kanban.db"
        tree = args.tree or root / "byterover-projects" / args.project / ".brv/context-tree"
        raw = args.raw or args.workspace / ".swarm/raw"
        rules = args.rules or args.workspace / ".swarm/SWARM_WIKI.md"
        out = args.out or args.workspace / ".swarm/wiki"
        sys.path.insert(0, str(args.hermes_source))
        from hermes_cli.kanban_db import VALID_STATUSES
        inputs = wiki.snapshot(db, tree, raw, rules)
        projection = wiki.Projection(inputs, args.project, args.board, args.workspace,
                                     args.repo or args.workspace, VALID_STATUSES, args.maintainer, args.task_workspace_root)
        files = projection.render()
        matched = wiki.publish(out, files, inputs, args.workspace, args.check)
        print(json.dumps({"output": str(out.absolute()), "pages": len(files), "findings": len(projection.findings),
                          "unresolved_findings": len(projection.unresolved_findings),
                          "audit_outcomes": {outcome: sum(f["outcome"] == outcome for f in projection.findings)
                                             for outcome in sorted({f["outcome"] for f in projection.findings})},
                          "check": args.check, "matches": matched}, sort_keys=True))
        for finding in projection.findings:
            print(json.dumps(finding, sort_keys=True), file=sys.stderr)
        return 1 if not matched or projection.unresolved_findings else 0
    except (ValueError, OSError, ImportError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print("swarm-wiki: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
