#!/usr/bin/env python3
"""Audit and narrowly repair off-enum Hermes Kanban task statuses.

Issue #129021 observed dispatcher workers writing tasks.status='completed' directly
after both sanctioned mutation paths were unavailable. This tool is intentionally
conservative: audit is the default; --apply only converts 'completed' -> 'done'
when the task already has completion evidence in task_runs and task_events.

A SQLite backup is created before any mutation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

VALID_STATUSES = {
    "triage",
    "todo",
    "scheduled",
    "ready",
    "running",
    "blocked",
    "review",
    "done",
    "archived",
}


def invalid_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in VALID_STATUSES)
    return list(
        conn.execute(
            f"""
            SELECT
                t.id,
                t.status,
                t.title,
                t.completed_at,
                EXISTS(
                    SELECT 1
                    FROM task_runs r
                    WHERE r.task_id = t.id
                      AND r.status = 'done'
                      AND r.outcome = 'completed'
                ) AS has_completed_run,
                EXISTS(
                    SELECT 1
                    FROM task_events e
                    WHERE e.task_id = t.id
                      AND e.kind = 'completed'
                ) AS has_completed_event
            FROM tasks t
            WHERE t.status IS NULL OR t.status NOT IN ({placeholders})
            ORDER BY t.id
            """,
            tuple(sorted(VALID_STATUSES)),
        )
    )


def repairable(row: sqlite3.Row) -> bool:
    return (
        row["status"] == "completed"
        and row["completed_at"] is not None
        and bool(row["has_completed_run"])
        and bool(row["has_completed_event"])
    )


def backup_database(db_path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.name}.pre-status-repair.{stamp}.bak")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit/repair off-enum Hermes Kanban task statuses from issue #129021."
    )
    parser.add_argument("--db", type=Path, required=True, help="Path to the board's kanban.db")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Repair only strongly evidenced status='completed' rows; audit is default.",
    )
    args = parser.parse_args()

    db_path = args.db.expanduser().resolve()
    if not db_path.exists():
        parser.error(f"database does not exist: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = invalid_rows(conn)
        if not rows:
            print("OK: no off-enum task statuses found")
            return 0

        for row in rows:
            verdict = "repairable" if repairable(row) else "manual-review"
            print(
                f"{row['id']}: status={row['status']!r} "
                f"completed_at={row['completed_at']!r} "
                f"completed_run={bool(row['has_completed_run'])} "
                f"completed_event={bool(row['has_completed_event'])} "
                f"[{verdict}]"
            )

        if not args.apply:
            print(f"AUDIT: {len(rows)} invalid row(s); rerun with --apply for strongly evidenced rows")
            return 2

        blocked = [row for row in rows if not repairable(row)]
        if blocked:
            print(
                "REFUSED: at least one invalid row lacks enough evidence for automatic repair; "
                "no rows changed"
            )
            return 3

        backup_path = backup_database(db_path)
        with conn:
            for row in rows:
                conn.execute(
                    "UPDATE tasks SET status='done' WHERE id=? AND status='completed'",
                    (row["id"],),
                )

        remaining = invalid_rows(conn)
        if remaining:
            raise RuntimeError("repair completed but invalid rows remain; restore the backup and inspect")

        print(f"REPAIRED: {len(rows)} row(s) completed -> done")
        print(f"BACKUP: {backup_path}")
        print("Run one dispatcher tick (or leave the gateway running) so dependent children are recomputed.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
