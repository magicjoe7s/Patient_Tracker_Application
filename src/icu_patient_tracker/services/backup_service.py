"""Application boundary for verified database backup and restore."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from icu_patient_tracker.persistence.backup import BackupManager
from icu_patient_tracker.persistence.exceptions import BackupError, RestoreError
from icu_patient_tracker.services.events import (
    EventPublisher,
    NullEventPublisher,
    PersistenceLifecycleEvent,
)
from icu_patient_tracker.services.exceptions import BackupServiceError


@dataclass(frozen=True, slots=True)
class BackupDescriptor:
    """Verified candidate identity shown before destructive restoration."""

    path: Path
    size_bytes: int
    sha256: str


class BackupService:
    """Coordinate safe backup operations and publish only successful completion."""

    def __init__(
        self,
        manager: BackupManager,
        publisher: EventPublisher | None = None,
        *,
        prepare_for_replace: Callable[[], None] | None = None,
        reopen_after_replace: Callable[[], None] | None = None,
    ) -> None:
        self._manager = manager
        self._publisher = publisher or NullEventPublisher()
        self._prepare_for_replace = prepare_for_replace
        self._reopen_after_replace = reopen_after_replace

    def create(self, *, label: str = "backup") -> Path:
        try:
            path = self._manager.create_backup(label=label)
        except BackupError as error:
            raise BackupServiceError("The database backup could not be created.") from error
        self._publisher.publish(PersistenceLifecycleEvent(path.name, "backup_completed"))
        return path

    def verify(self, path: Path) -> bool:
        return self._manager.verify_backup(path)

    def inspect(self, path: Path) -> BackupDescriptor:
        candidate = path.expanduser().resolve()
        try:
            if not self._manager.verify_backup(candidate):
                raise BackupError("The candidate backup is corrupt or unsupported.")
            return BackupDescriptor(
                candidate,
                candidate.stat().st_size,
                self._manager.file_sha256(candidate),
            )
        except (OSError, BackupError) as error:
            raise BackupServiceError(
                "The selected file is not a valid ICU Patient Tracker backup."
            ) from error

    def restore(
        self,
        path: Path,
        *,
        prepare_for_replace: Callable[[], None] | None = None,
        expected_sha256: str | None = None,
    ) -> Path:
        prepared = False

        def prepare() -> None:
            nonlocal prepared
            callback = prepare_for_replace or self._prepare_for_replace
            if callback is not None:
                callback()
                prepared = True

        try:
            safety_backup = self._manager.restore_backup(
                path,
                prepare_for_replace=prepare,
                expected_sha256=expected_sha256,
            )
        except (BackupError, RestoreError) as error:
            raise BackupServiceError("The database backup could not be restored.") from error
        finally:
            if prepared and self._reopen_after_replace is not None:
                try:
                    self._reopen_after_replace()
                except Exception as error:
                    raise BackupServiceError(
                        "The database was replaced but could not be reopened."
                    ) from error
        self._publisher.publish(PersistenceLifecycleEvent(path.name, "restore_completed"))
        return safety_backup
