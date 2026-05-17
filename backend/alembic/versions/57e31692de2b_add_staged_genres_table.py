"""add staged_genres table

Revision ID: 57e31692de2b
Revises: a1b2c3d4e5f6
Create Date: 2026-04-06 22:14:02.839541

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57e31692de2b'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ``staged_genres`` table at the pre-suggested_artist/title shape.

    The original revision shipped empty (``pass``), which made
    ``alembic upgrade head`` blow up on fresh installs once the next revision
    (``93ccb6e1d378``) tried to ``ALTER TABLE staged_genres``. Existing
    installs got the table via ``Base.metadata.create_all`` at boot, so the
    bug only bit fresh checkouts and CI. We backfill the create here so the
    migration chain works from base; existing DBs are unaffected because
    alembic_version already points past this revision and replays nothing.

    The shape mirrors the table *at this point in history* — the
    ``suggested_artist`` and ``suggested_title`` columns are added by the
    next revision and dropped by the one after. The idempotency guard means
    a fresh install whose ``init_db()`` already created the table via
    ``create_all`` won't get a duplicate.
    """
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        existing = conn.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='staged_genres'")
        ).fetchone()
        if existing:
            return

    op.create_table(
        "staged_genres",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lexicon_track_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("suggested_genre", sa.String(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lexicon_track_id"),
    )
    op.create_index(op.f("ix_staged_genres_id"), "staged_genres", ["id"], unique=False)
    op.create_index(
        op.f("ix_staged_genres_lexicon_track_id"),
        "staged_genres",
        ["lexicon_track_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop ``staged_genres`` (and its indexes)."""
    op.drop_index(op.f("ix_staged_genres_lexicon_track_id"), table_name="staged_genres")
    op.drop_index(op.f("ix_staged_genres_id"), table_name="staged_genres")
    op.drop_table("staged_genres")
