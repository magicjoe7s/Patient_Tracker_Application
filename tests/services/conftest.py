"""Temporary application-service persistence boundary."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from icu_patient_tracker.persistence.database import DatabaseManager


@pytest.fixture
def database_manager(tmp_path: Path) -> Iterator[DatabaseManager]:
    manager = DatabaseManager(tmp_path / "services.sqlite3")
    manager.initialize()
    yield manager
    manager.dispose()
