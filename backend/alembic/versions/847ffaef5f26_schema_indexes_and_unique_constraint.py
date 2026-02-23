"""schema indexes and unique constraint

Revision ID: 847ffaef5f26
Revises: f80e4bd6cc8e
Create Date: 2026-02-22 19:27:06.869382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '847ffaef5f26'
down_revision: Union[str, Sequence[str], None] = 'f80e4bd6cc8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes, unique constraint on tracks, and updated_at columns."""
    op.create_index(
        op.f("ix_tracks_spotify_id"),
        "tracks",
        ["spotify_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tracks_playlist_id"),
        "tracks",
        ["playlist_id"],
        unique=False,
    )
    op.create_index(
        "uq_tracks_playlist_spotify_id",
        "tracks",
        ["playlist_id", "spotify_id"],
        unique=True,
    )
    op.add_column(
        "playlists",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tracks",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Remove indexes, unique constraint, and updated_at columns."""
    op.drop_column("tracks", "updated_at")
    op.drop_column("playlists", "updated_at")
    op.drop_index("uq_tracks_playlist_spotify_id", table_name="tracks")
    op.drop_index(op.f("ix_tracks_playlist_id"), table_name="tracks")
    op.drop_index(op.f("ix_tracks_spotify_id"), table_name="tracks")
