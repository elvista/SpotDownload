"""initial schema

Revision ID: f80e4bd6cc8e
Revises:
Create Date: 2026-02-22 19:26:16.667537

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f80e4bd6cc8e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create playlists, tracks, app_settings tables."""
    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("spotify_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("track_count", sa.Integer(), nullable=True),
        sa.Column("spotify_url", sa.String(), nullable=True),
        sa.Column("is_monitoring", sa.Boolean(), nullable=True),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spotify_id"),
    )
    op.create_index(op.f("ix_playlists_spotify_id"), "playlists", ["spotify_id"], unique=True)
    op.create_index(op.f("ix_playlists_id"), "playlists", ["id"], unique=False)

    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("playlist_id", sa.Integer(), nullable=False),
        sa.Column("spotify_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("album", sa.String(), nullable=True),
        sa.Column("genre", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("spotify_url", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=True),
        sa.Column("is_downloaded", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["playlist_id"], ["playlists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tracks_id"), "tracks", ["id"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("tracks")
    op.drop_table("playlists")
    op.drop_table("app_settings")
