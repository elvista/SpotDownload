"""Regression test for the alembic migration chain.

Fresh installs run ``alembic upgrade head`` against an empty SQLite file.
The chain has historically broken at ``93ccb6e1d378`` (ALTER TABLE
staged_genres) because the prior revision created the table only as
``pass``. This test exercises the full chain end-to-end so the next
broken-from-base regression is caught in CI rather than at the founder's
fresh-machine setup.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_alembic_upgrade_head_from_empty_db(tmp_path):
    db_file = tmp_path / "alembic_chain.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"

    # Confirm DB is empty going in.
    assert not db_file.exists()

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    # All expected tables exist after upgrade.
    import sqlite3

    con = sqlite3.connect(str(db_file))
    try:
        tables = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        con.close()

    expected = {
        "alembic_version",
        "playlists",
        "tracks",
        "app_settings",
        "staged_genres",
    }
    missing = expected - tables
    assert not missing, f"missing tables after upgrade head: {missing}"


def test_alembic_downgrade_base_then_upgrade_head_round_trip(tmp_path):
    """Upgrade → downgrade base → upgrade again all work without a crash."""
    db_file = tmp_path / "alembic_round_trip.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"

    for args in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
        result = subprocess.run(
            ["alembic", *args],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
