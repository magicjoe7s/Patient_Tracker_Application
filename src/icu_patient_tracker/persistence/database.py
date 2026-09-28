"""SQLite engine lifecycle, safety pragmas, migrations, and unit-of-work creation."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from icu_patient_tracker.persistence.unit_of_work import SqlAlchemyUnitOfWork


class DatabaseManager:
    """Own the configured SQLite engine without exposing sessions to callers."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.expanduser().resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(__name__)
        self._engine: Engine = create_engine(
            URL.create("sqlite", database=str(self._database_path)),
            connect_args={"timeout": 30.0, "check_same_thread": False},
            pool_pre_ping=True,
        )
        self._configure_sqlite_connections()
        self._session_factory = sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def database_path(self) -> Path:
        """Return the absolute configured database path."""
        return self._database_path

    def initialize(self) -> None:
        """Create or formally migrate the database to the current schema revision."""
        from icu_patient_tracker.persistence.migration_manager import MigrationManager

        self._logger.info("Database initialization started")
        MigrationManager(self._database_path).upgrade()
        self.verify_connection()
        self._logger.info("Database initialization complete")

    def verify_connection(self) -> None:
        """Verify basic connectivity and required foreign-key enforcement."""
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                foreign_keys_enabled = connection.scalar(text("PRAGMA foreign_keys"))
                if foreign_keys_enabled != 1:
                    raise RuntimeError("SQLite foreign-key enforcement is disabled.")
        except (SQLAlchemyError, RuntimeError):
            self._logger.exception("Database connection verification failed")
            raise

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """Create an isolated transaction boundary with database-agnostic repositories."""
        return SqlAlchemyUnitOfWork(self._session_factory)

    def sqlite_settings(self) -> dict[str, str | int]:
        """Return connection safety settings without exposing a live connection."""
        with self._engine.connect() as connection:
            return {
                "foreign_keys": int(connection.scalar(text("PRAGMA foreign_keys")) or 0),
                "journal_mode": str(connection.scalar(text("PRAGMA journal_mode"))),
                "synchronous": int(connection.scalar(text("PRAGMA synchronous")) or 0),
                "busy_timeout": int(connection.scalar(text("PRAGMA busy_timeout")) or 0),
            }

    def dispose(self) -> None:
        """Release all pooled connections before shutdown or database replacement."""
        self._engine.dispose()

    def _configure_sqlite_connections(self) -> None:
        @event.listens_for(self._engine, "connect")
        def set_sqlite_pragmas(
            dbapi_connection: sqlite3.Connection, connection_record: Any
        ) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
                cursor.execute("PRAGMA busy_timeout = 5000")
            finally:
                cursor.close()
