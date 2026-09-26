#!/usr/bin/env python3
"""Online SQLite backup used by backup_loop.sh.

Usage: backup_db.py DB_PATH OUT_DIR [KEEP]

Uses sqlite3's online backup API (safe against a live WAL writer) and keeps only
the newest KEEP snapshots. Exits non-zero on failure but never corrupts state.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import time


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: backup_db.py DB_PATH OUT_DIR [KEEP]", file=sys.stderr)
        return 2
    db_path = pathlib.Path(sys.argv[1])
    out_dir = pathlib.Path(sys.argv[2])
    keep = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    if not db_path.exists():
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = out_dir / f"jobs.backup-{stamp}.db"

    source = sqlite3.connect(str(db_path), timeout=30)
    target = sqlite3.connect(str(dest))
    try:
        with target:
            source.backup(target)
    finally:
        target.close()
        source.close()

    snapshots = sorted(out_dir.glob("jobs.backup-*.db"))
    for old in snapshots[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)

    print(f"[backup] wrote {dest.name} ({len(snapshots[-keep:]) if keep > 0 else len(snapshots)} kept)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[backup] failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
