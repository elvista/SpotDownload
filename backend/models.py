from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
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
    last_checked = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tracks = relationship("Track", back_populates="playlist", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), nullable=False)
    spotify_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    artist = Column(String, nullable=False)
    album = Column(String, default="")
    duration_ms = Column(Integer, default=0)
    image_url = Column(String, default="")
    spotify_url = Column(String, default="")
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_new = Column(Boolean, default=False)
    is_downloaded = Column(Boolean, default=False)

    playlist = relationship("Playlist", back_populates="tracks")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, nullable=False)
    value = Column(Text, default="")
