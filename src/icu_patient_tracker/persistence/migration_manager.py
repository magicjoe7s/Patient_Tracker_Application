"""Formal Alembic schema migration management and revision safety checks."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import URL, create_engine
from sqlalchemy.exc import SQLAlchemyError

from icu_patient_tracker.app.config import ConfigManager
from icu_patient_tracker.persistence.exceptions import (
    MigrationError,
    UnsupportedSchemaVersionError,
)

CURRENT_SCHEMA_REVISION = "0014_clinical_sync"


class MigrationManager:
    """Upgrade, inspect, and safely downgrade one configured SQLite schema."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.expanduser().resolve()
        self._logger = logging.getLogger(__name__)
        self._configuration = self._create_configuration()

    def upgrade(self, target_revision: str = "head") -> None:
        """Upgrade through formal revisions after rejecting unknown future schemas."""
        self.ensure_supported_schema()
        self._logger.info("Database migration started: target=%s", target_revision)
        try:
            command.upgrade(self._configuration, target_revision)
        except (CommandError, SQLAlchemyError) as error:
            self._logger.exception("Database migration failed")
            raise MigrationError("Database schema upgrade failed.") from error
        self._logger.info("Database migration completed: revision=%s", self.current_revision())

    def downgrade(self, target_revision: str) -> None:
        """Downgrade explicitly when a revision supplies a safe reversal."""
        self.ensure_supported_schema()
        try:
            command.downgrade(self._configuration, target_revision)
        except (CommandError, SQLAlchemyError) as error:
            self._logger.exception("Database downgrade failed")
            raise MigrationError("Database schema downgrade failed.") from error

    def current_revision(self) -> str | None:
        """Return the database's recorded Alembic revision, if initialized."""
        if not self._database_path.exists():
            return None
        engine = create_engine(URL.create("sqlite", database=str(self._database_path)))
        try:
            with engine.connect() as connection:
                return MigrationContext.configure(connection).get_current_revision()
        except SQLAlchemyError as error:
            raise MigrationError("Database schema revision could not be inspected.") from error
        finally:
            engine.dispose()

    def ensure_supported_schema(self) -> None:
        """Reject a revision not present in the packaged migration history."""
        revision = self.current_revision()
        if revision is None:
            return
        known_revisions = {
            migration.revision
            for migration in ScriptDirectory.from_config(self._configuration).walk_revisions()
        }
        if revision not in known_revisions:
            self._logger.error("Unsupported database schema detected: revision=%s", revision)
            raise UnsupportedSchemaVersionError(
                f"Database schema revision {revision!r} is not supported."
            )

    def _create_configuration(self) -> Config:
        configuration = Config()
        migration_directory = Path(__file__).with_name("migrations")
        configuration.set_main_option("script_location", str(migration_directory))
        database_url = str(URL.create("sqlite", database=str(self._database_path)))
        configuration.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        return configuration


def main(arguments: Sequence[str] | None = None) -> int:
    """Run documented migration commands against the configured application database."""
    parser = argparse.ArgumentParser(description="Manage ICU Patient Tracker schema revisions.")
    parser.add_argument("command", choices=("upgrade", "downgrade", "current"))
    parser.add_argument("revision", nargs="?", default="head")
    parsed = parser.parse_args(arguments)
    config = ConfigManager().load()
    manager = MigrationManager(config.database_path)
    if parsed.command == "upgrade":
        manager.upgrade(parsed.revision)
    elif parsed.command == "downgrade":
        manager.downgrade(parsed.revision)
    else:
        print(manager.current_revision() or "uninitialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
