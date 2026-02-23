"""Pytest fixtures for SpotDownload API tests."""

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import models  # noqa: F401 - register models with Base

# Import before app so we can create tables on test engine
from database import Base, get_db

# Set test DB before importing app (so scheduler uses test DB if it runs)
TEST_DB_URL = "sqlite:///./test_spotdownload.db"
os.environ.setdefault("DATABASE_URL", TEST_DB_URL)

from main import app  # noqa: E402

# Test engine and session (file-based so same DB for whole run)
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db() -> Generator[Session, None, None]:
    """Provide test database session."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def setup_test_db():
    """Create test database tables once per session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    try:
        os.remove("./test_spotdownload.db")
    except OSError:
        pass


@pytest.fixture
def db_session(setup_test_db) -> Generator[Session, None, None]:
    """Fresh database session per test (rollback after each test)."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    """HTTP client with overridden get_db using test session."""

    def get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = get_db_override
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
