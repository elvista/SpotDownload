from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    spotify_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    owner = Column(String, default="")
    image_url = Column(String, default="")
    track_count = Column(Integer, default=0)
    spotify_url = Column(String, default="")
    is_monitoring = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=lambda: datetime.now(UTC))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    tracks = relationship("Track", back_populates="playlist", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), nullable=False)
    spotify_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    artist = Column(String, nullable=False)
    album = Column(String, default="")
    genre = Column(String, default="")
    duration_ms = Column(Integer, default=0)
    image_url = Column(String, default="")
    spotify_url = Column(String, default="")
    added_at = Column(DateTime, default=lambda: datetime.now(UTC))
    is_new = Column(Boolean, default=False)
    is_downloaded = Column(Boolean, default=False)
    updated_at = Column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    playlist = relationship("Playlist", back_populates="tracks")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, nullable=False)
    value = Column(Text, default="")


class StagedGenre(Base):
    __tablename__ = "staged_genres"

    id = Column(Integer, primary_key=True, index=True)
    lexicon_track_id = Column(Integer, nullable=False, index=True, unique=True)
    title = Column(String, nullable=False)
    artist = Column(String, nullable=False)
    suggested_genre = Column(String, nullable=False)
    approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# --- Upscale section --------------------------------------------------------
# Five tables added by the Upscale feature. Status defaults and nullable
# `confidence` are load-bearing for the AI slice plug-in point; do not change
# without coordinating with the AI slice.


class LibraryFile(Base):
    __tablename__ = "library_files"

    id = Column(Integer, primary_key=True, index=True)
    abs_path = Column(String, nullable=False, unique=True, index=True)
    sha256 = Column(String, nullable=False, index=True)
    size_bytes = Column(Integer, nullable=False)
    bitrate_kbps = Column(Integer, nullable=False, index=True)
    duration_s = Column(Float)
    mtime_ns = Column(BigInteger, nullable=False)
    tag_title = Column(String, default="")
    tag_artist = Column(String, default="")
    tag_album = Column(String, default="")
    last_scanned = Column(DateTime, default=lambda: datetime.now(UTC))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class PoolCredential(Base):
    __tablename__ = "pool_credentials"

    pool_slug = Column(String, primary_key=True)
    state_blob = Column(Text, nullable=False)
    last_login = Column(DateTime, default=lambda: datetime.now(UTC))
    last_error = Column(Text, default="")


class UpscaleMatch(Base):
    __tablename__ = "upscale_matches"

    id = Column(Integer, primary_key=True, index=True)
    library_file_id = Column(
        Integer, ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pool_slug = Column(String, nullable=False)
    pool_hit_id = Column(String, nullable=False)
    pool_title = Column(String, nullable=False)
    pool_artist = Column(String, nullable=False)
    pool_bitrate_kbps = Column(Integer, nullable=False)
    pool_format = Column(String, nullable=False)
    pool_preview_url = Column(String, default="")  # cached so /preview can stream without re-search
    confidence = Column(Float)  # populated by AI slice; null in Phase 1
    status = Column(String, default="candidate")  # candidate|confirmed|rejected|replaced
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint(
            "library_file_id", "pool_slug", "pool_hit_id", name="uq_upscale_matches_lib_pool_hit"
        ),
    )


class ReplaceLog(Base):
    __tablename__ = "replace_logs"

    id = Column(Integer, primary_key=True, index=True)
    library_file_id = Column(
        Integer, ForeignKey("library_files.id", ondelete="SET NULL"), index=True
    )
    upscale_match_id = Column(Integer, ForeignKey("upscale_matches.id", ondelete="SET NULL"))
    abs_path = Column(String, nullable=False)
    archive_path = Column(String, nullable=False)
    old_bitrate_kbps = Column(Integer, nullable=False)
    new_bitrate_kbps = Column(Integer, nullable=False)
    old_sha256 = Column(String, nullable=False)
    new_sha256 = Column(String, nullable=False)
    pool_slug = Column(String, nullable=False)
    pool_source_url = Column(String, default="")
    file_size_before = Column(BigInteger, default=0)  # bytes; 0 if unknown
    file_size_after = Column(BigInteger, default=0)
    id3_copy_status = Column(String, default="ok")  # 'ok' | 'partial' | 'failed'
    replaced_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=lambda: datetime.now(UTC))
    finished_at = Column(DateTime)
    root_path = Column(String, nullable=False)
    files_seen = Column(Integer, default=0)
    candidates = Column(Integer, default=0)
    error = Column(Text, default="")
