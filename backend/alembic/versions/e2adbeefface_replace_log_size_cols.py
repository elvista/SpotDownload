"""replace_logs: add file_size_before + file_size_after

Revision ID: e2adbeefface
Revises: d1ade2b00b5e
Create Date: 2026-05-17 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e2adbeefface"
down_revision: Union[str, Sequence[str], None] = "d1ade2b00b5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add byte-size columns so the Replace Log answers 'how much bigger?' on its own."""
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        cols = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(replace_logs)")).fetchall()]
        if "file_size_before" not in cols:
            op.add_column(
                "replace_logs", sa.Column("file_size_before", sa.BigInteger(), nullable=True)
            )
        if "file_size_after" not in cols:
            op.add_column(
                "replace_logs", sa.Column("file_size_after", sa.BigInteger(), nullable=True)
            )
        return
    op.add_column("replace_logs", sa.Column("file_size_before", sa.BigInteger(), nullable=True))
    op.add_column("replace_logs", sa.Column("file_size_after", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("replace_logs", "file_size_after")
    op.drop_column("replace_logs", "file_size_before")
