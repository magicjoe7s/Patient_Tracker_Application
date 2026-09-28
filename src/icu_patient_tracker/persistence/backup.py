"""Consistent SQLite backup, verification, retention, and safe restoration."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from icu_patient_tracker.persistence.exceptions import (
    BackupError,
    MigrationError,
    RestoreError,
)
from icu_patient_tracker.persistence.migration_manager import MigrationManager


class BackupManager:
    """Create and restore verified SQLite snapshots using SQLite's online backup API."""

    def __init__(
        self,
        database_path: Path,
        backup_directory: Path,
        *,
        retention_count: int = 10,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if retention_count < 1:
            raise ValueError("retention_count must be at least 1.")
        self._database_path = database_path.expanduser().resolve()
        self._backup_directory = backup_directory.expanduser().resolve()
        self._retention_count = retention_count
        self._now = now or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger(__name__)

    def create_backup(self, *, label: str = "backup") -> Path:
        """Create, verify, atomically publish, and retain a consistent snapshot."""
        return self._create_backup(label=label, additional_protected=set())

    def _create_backup(self, *, label: str, additional_protected: set[Path]) -> Path:
        if not self._database_path.is_file():
            raise BackupError(f"Active database does not exist: {self._database_path}")
        normalized_label = self._normalize_label(label)
        self._backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = self._backup_directory / (
            f"icu_patient_tracker_{normalized_label}_{timestamp}.sqlite3"
        )
        temporary = destination.with_suffix(".sqlite3.tmp")
        self._logger.info("Database backup creation started: backup=%s", destination.name)
        try:
            self._backup_database(self._database_path, temporary)
            self._verify_or_raise(temporary)
            os.replace(temporary, destination)
            self._enforce_retention(protected={destination, *additional_protected})
        except (OSError, sqlite3.Error, MigrationError, BackupError) as error:
            temporary.unlink(missing_ok=True)
            self._logger.exception("Database backup creation failed")
            if isinstance(error, BackupError):
                raise
            raise BackupError("A consistent database backup could not be created.") from error
        self._logger.info("Database backup created: backup=%s", destination.name)
        return destination

    def verify_backup(self, backup_path: Path) -> bool:
        """Return whether a candidate is readable, internally consistent, and versioned."""
        try:
            self._verify_or_raise(backup_path.expanduser().resolve())
        except (OSError, sqlite3.Error, MigrationError, BackupError):
            self._logger.warning("Database backup verification failed: backup=%s", backup_path.name)
            return False
        self._logger.info("Database backup verified: backup=%s", backup_path.name)
        return True

    def restore_backup(
        self,
        backup_path: Path,
        *,
        prepare_for_replace: Callable[[], None] | None = None,
        expected_sha256: str | None = None,
    ) -> Path:
        """Validate in isolation, preserve current data, then atomically replace the database."""
        candidate = backup_path.expanduser().resolve()
        self._logger.info("Database restore started: backup=%s", candidate.name)
        if expected_sha256 is not None and self.file_sha256(candidate) != expected_sha256:
            raise RestoreError("The backup changed after it was reviewed.")
        if not self.verify_backup(candidate):
            self._logger.error(
                "Database restore rejected before replacement: backup=%s", candidate.name
            )
            raise RestoreError("The candidate backup is corrupt or unsupported.")

        try:
            pre_restore_backup = self._create_backup(
                label="pre_restore", additional_protected={candidate}
            )
            temporary = self._database_path.with_suffix(".restore.tmp")
            temporary.unlink(missing_ok=True)
            self._backup_database(candidate, temporary)
            self._verify_or_raise(temporary)
            if expected_sha256 is not None and self.file_sha256(candidate) != expected_sha256:
                raise RestoreError("The backup changed while it was being prepared.")
            self._enforce_retention(protected={candidate, pre_restore_backup})
            if prepare_for_replace is not None:
                prepare_for_replace()
            self._checkpoint_active_database()
            self._remove_active_sidecars()
            os.replace(temporary, self._database_path)
        except Exception as error:
            self._database_path.with_suffix(".restore.tmp").unlink(missing_ok=True)
            self._logger.exception("Database restore failed; active database was preserved")
            raise RestoreError("The database backup could not be restored safely.") from error

        self._logger.info(
            "Database restore completed: backup=%s pre_restore=%s",
            candidate.name,
            pre_restore_backup.name,
        )
        return pre_restore_backup

    @staticmethod
    def file_sha256(path: Path) -> str:
        """Return a content identity used to bind review to destructive replacement."""
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as error:
            raise BackupError("The backup candidate could not be read.") from error
        return digest.hexdigest()

    @staticmethod
    def _backup_database(source_path: Path, destination_path: Path) -> None:
        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as source,
            closing(sqlite3.connect(destination_path)) as destination,
        ):
            source.backup(destination)

    @staticmethod
    def _normalize_label(label: str) -> str:
        normalized = label.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]+", normalized):
            raise BackupError("Backup label may contain only letters, numbers, '_' and '-'.")
        return normalized

    @staticmethod
    def _verify_or_raise(candidate: Path) -> None:
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise BackupError("Backup candidate is missing or empty.")
        candidate_uri = f"file:{candidate.as_posix()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(candidate_uri, uri=True)) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise BackupError("SQLite integrity verification failed.")
        migration_manager = MigrationManager(candidate)
        migration_manager.ensure_supported_schema()
        if migration_manager.current_revision() is None:
            raise BackupError("Backup candidate has no schema revision.")

    def _enforce_retention(self, *, protected: set[Path]) -> None:
        backups = sorted(
            self._backup_directory.glob("icu_patient_tracker_*.sqlite3"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        retained = 0
        for backup in backups:
            if backup in protected:
                continue
            retained += 1
            if retained >= self._retention_count:
                backup.unlink()

    def _checkpoint_active_database(self) -> None:
        with closing(sqlite3.connect(self._database_path)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _remove_active_sidecars(self) -> None:
        for suffix in ("-wal", "-shm"):
            Path(f"{self._database_path}{suffix}").unlink(missing_ok=True)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run documented backup commands against configured application data."""
    from icu_patient_tracker.app.config import ConfigManager
    from icu_patient_tracker.persistence.database import DatabaseManager

    parser = argparse.ArgumentParser(description="Manage ICU Patient Tracker backups.")
    parser.add_argument("command", choices=("create", "verify", "restore"))
    parser.add_argument("backup", nargs="?", type=Path)
    parsed = parser.parse_args(arguments)
    config = ConfigManager().load()
    manager = BackupManager(
        config.database_path,
        config.backup_directory,
        retention_count=config.backup_retention_count,
    )
    if parsed.command == "create":
        print(manager.create_backup())
        return 0
    if parsed.backup is None:
        parser.error("verify and restore require a backup path")
    if parsed.command == "verify":
        return 0 if manager.verify_backup(parsed.backup) else 1

    database = DatabaseManager(config.database_path)
    manager.restore_backup(parsed.backup, prepare_for_replace=database.dispose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
