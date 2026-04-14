"""Pytest fixtures for testing."""

import pytest
from pathlib import Path

from app.infrastructure.database import Database


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Return a test database path.

    Args:
        tmp_path: pytest's temporary path fixture.

    Returns:
        Path to a test database file.
    """
    return str(tmp_path / "test.db")


@pytest.fixture
def db(db_path: str) -> Database:
    """Initialize and return a Database instance.

    Args:
        db_path: The database path fixture.

    Returns:
        A Database instance configured for testing.
    """
    return Database(db_path)


# Fixtures for future tasks (Tasks 5-8)
# These will be implemented in later tasks


@pytest.fixture
def task_repo(db: Database):
    """Return a SQLiteTaskRepository instance.

    Args:
        db: The database fixture.

    Returns:
        A SQLiteTaskRepository instance.
    """
    from app.infrastructure.sqlite_repository import SQLiteTaskRepository

    repo = SQLiteTaskRepository(db)
    return repo


@pytest.fixture
def message_bus(db: Database):
    """Return a SQLiteMessageBus instance.

    This fixture will be implemented in Task 7.

    Args:
        db: The database fixture.

    Returns:
        A SQLiteMessageBus instance.
    """
    # Will be: from app.infrastructure.message_bus import SQLiteMessageBus
    # return SQLiteMessageBus(db)
    pytest.skip("message_bus fixture will be implemented in Task 7")


@pytest.fixture
def event_store(db: Database):
    """Return a SQLiteEventStore instance.

    This fixture will be implemented in Task 6.

    Args:
        db: The database fixture.

    Returns:
        A SQLiteEventStore instance.
    """
    # Will be: from app.infrastructure.event_store import SQLiteEventStore
    # return SQLiteEventStore(db)
    pytest.skip("event_store fixture will be implemented in Task 6")


@pytest.fixture
def workflow_repo(db: Database):
    """Return a SQLiteWorkflowRepo instance.

    This fixture will be implemented in Task 8.

    Args:
        db: The database fixture.

    Returns:
        A SQLiteWorkflowRepo instance.
    """
    # Will be: from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
    # return SQLiteWorkflowRepo(db)
    pytest.skip("workflow_repo fixture will be implemented in Task 8")
