"""upscale: add library_files, pool_credentials, upscale_matches, replace_logs, scan_runs

Revision ID: c0ffee01ade1
Revises: ae784ec4380e
Create Date: 2026-05-17 04:45:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0ffee01ade1"
down_revision: Union[str, Sequence[str], None] = "ae784ec4380e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the five Upscale section tables. All additive — no existing tables touched."""
    op.create_table(
        "library_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("abs_path", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("tag_title", sa.String(), nullable=True),
        sa.Column("tag_artist", sa.String(), nullable=True),
        sa.Column("tag_album", sa.String(), nullable=True),
        sa.Column("last_scanned", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("abs_path"),
    )
    op.create_index(op.f("ix_library_files_id"), "library_files", ["id"], unique=False)
    op.create_index(
        op.f("ix_library_files_abs_path"), "library_files", ["abs_path"], unique=True
    )
    op.create_index(op.f("ix_library_files_sha256"), "library_files", ["sha256"], unique=False)
    op.create_index(
        op.f("ix_library_files_bitrate_kbps"), "library_files", ["bitrate_kbps"], unique=False
    )

    op.create_table(
        "pool_credentials",
        sa.Column("pool_slug", sa.String(), nullable=False),
        sa.Column("state_blob", sa.Text(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("pool_slug"),
    )

    op.create_table(
        "upscale_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_file_id", sa.Integer(), nullable=False),
        sa.Column("pool_slug", sa.String(), nullable=False),
        sa.Column("pool_hit_id", sa.String(), nullable=False),
        sa.Column("pool_title", sa.String(), nullable=False),
        sa.Column("pool_artist", sa.String(), nullable=False),
        sa.Column("pool_bitrate_kbps", sa.Integer(), nullable=False),
        sa.Column("pool_format", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["library_file_id"], ["library_files.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "library_file_id",
            "pool_slug",
            "pool_hit_id",
            name="uq_upscale_matches_lib_pool_hit",
        ),
    )
    op.create_index(op.f("ix_upscale_matches_id"), "upscale_matches", ["id"], unique=False)
    op.create_index(
        op.f("ix_upscale_matches_library_file_id"),
        "upscale_matches",
        ["library_file_id"],
        unique=False,
    )

    op.create_table(
        "replace_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_file_id", sa.Integer(), nullable=True),
        sa.Column("upscale_match_id", sa.Integer(), nullable=True),
        sa.Column("abs_path", sa.String(), nullable=False),
        sa.Column("archive_path", sa.String(), nullable=False),
        sa.Column("old_bitrate_kbps", sa.Integer(), nullable=False),
        sa.Column("new_bitrate_kbps", sa.Integer(), nullable=False),
        sa.Column("old_sha256", sa.String(), nullable=False),
        sa.Column("new_sha256", sa.String(), nullable=False),
        sa.Column("pool_slug", sa.String(), nullable=False),
        sa.Column("pool_source_url", sa.String(), nullable=True),
        sa.Column("id3_copy_status", sa.String(), nullable=True),
        sa.Column("replaced_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["library_file_id"], ["library_files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["upscale_match_id"], ["upscale_matches.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_replace_logs_id"), "replace_logs", ["id"], unique=False)
    op.create_index(
        op.f("ix_replace_logs_library_file_id"),
        "replace_logs",
        ["library_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_replace_logs_replaced_at"), "replace_logs", ["replaced_at"], unique=False
    )

    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column("files_seen", sa.Integer(), nullable=True),
        sa.Column("candidates", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scan_runs_id"), "scan_runs", ["id"], unique=False)


def downgrade() -> None:
    """Drop the five Upscale tables. Order respects FK dependencies."""
    op.drop_index(op.f("ix_scan_runs_id"), table_name="scan_runs")
    op.drop_table("scan_runs")

    op.drop_index(op.f("ix_replace_logs_replaced_at"), table_name="replace_logs")
    op.drop_index(op.f("ix_replace_logs_library_file_id"), table_name="replace_logs")
    op.drop_index(op.f("ix_replace_logs_id"), table_name="replace_logs")
    op.drop_table("replace_logs")

    op.drop_index(
        op.f("ix_upscale_matches_library_file_id"), table_name="upscale_matches"
    )
    op.drop_index(op.f("ix_upscale_matches_id"), table_name="upscale_matches")
    op.drop_table("upscale_matches")

    op.drop_table("pool_credentials")

    op.drop_index(op.f("ix_library_files_bitrate_kbps"), table_name="library_files")
    op.drop_index(op.f("ix_library_files_sha256"), table_name="library_files")
    op.drop_index(op.f("ix_library_files_abs_path"), table_name="library_files")
    op.drop_index(op.f("ix_library_files_id"), table_name="library_files")
    op.drop_table("library_files")
