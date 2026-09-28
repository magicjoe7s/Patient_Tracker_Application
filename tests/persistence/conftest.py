"""Temporary database fixtures for persistence tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from icu_patient_tracker.persistence.database import DatabaseManager


@pytest.fixture
def database_manager(tmp_path: Path) -> Iterator[DatabaseManager]:
    """Provide a migrated temporary database and close all connections afterward."""
    manager = DatabaseManager(tmp_path / "tracker.sqlite3")
    manager.initialize()
    yield manager
    manager.dispose()
