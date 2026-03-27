"""SQLAlchemy engine, session factory, and base for SpotDownload models."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

# SQLite is single-writer; for high concurrency consider PostgreSQL and pool_size.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_wal_on_connect(dbapi_conn, connection_record) -> None:
    if not str(settings.DATABASE_URL).startswith("sqlite"):
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    # NORMAL trades a small amount of crash durability for fewer fsyncs vs FULL.
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yield a DB session and close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables from models. Safe to call multiple times."""
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
