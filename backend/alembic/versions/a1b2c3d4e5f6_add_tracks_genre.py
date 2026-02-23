"""add tracks genre

Revision ID: a1b2c3d4e5f6
Revises: 847ffaef5f26
Create Date: 2026-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "847ffaef5f26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add genre column to tracks if missing (e.g. DB created before initial migration)."""
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        # SQLite: check if column exists
        cursor = conn.execute(sa.text("PRAGMA table_info(tracks)"))
        columns = [row[1] for row in cursor.fetchall()]
        if "genre" not in columns:
            op.add_column("tracks", sa.Column("genre", sa.String(), nullable=True))
    else:
        op.add_column("tracks", sa.Column("genre", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tracks", "genre")
