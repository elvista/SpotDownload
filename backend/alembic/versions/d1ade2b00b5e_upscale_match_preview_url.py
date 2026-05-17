"""upscale_matches: add pool_preview_url column

Revision ID: d1ade2b00b5e
Revises: c0ffee01ade1
Create Date: 2026-05-17 14:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1ade2b00b5e"
down_revision: Union[str, Sequence[str], None] = "c0ffee01ade1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ``pool_preview_url`` so /preview can stream after the fact."""
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        cols = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(upscale_matches)")).fetchall()]
        if "pool_preview_url" in cols:
            return
    op.add_column("upscale_matches", sa.Column("pool_preview_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("upscale_matches", "pool_preview_url")
