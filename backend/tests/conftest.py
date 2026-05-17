"""Pytest fixtures for CrateDigger API tests."""

import os
from collections.abc import Generator

# Set DATABASE_URL BEFORE any app import. ``database.py`` reads the value at
# import time when it constructs the engine, so setting it any later would
# leave ``SessionLocal`` bound to the dev DB and tests using the production
# session factory would write to the wrong file.
TEST_DB_URL = "sqlite:///./test_cratedigger.db"
os.environ.setdefault("DATABASE_URL", TEST_DB_URL)

import pytest  # noqa: E402, I001
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402, I001
import models  # noqa: E402, F401, I001  - register models with Base
from database import Base, engine as production_engine, get_db  # noqa: E402, I001
from main import app  # noqa: E402, I001

# Reuse the production engine — it's already bound to TEST_DB_URL because we
# set DATABASE_URL above before any app import. Sharing one engine + pool
# avoids "database is locked" errors when a test opens its own SessionLocal
# while a fixture-owned connection still holds a SQLite write transaction.
test_engine = production_engine
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
        os.remove("./test_cratedigger.db")
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
