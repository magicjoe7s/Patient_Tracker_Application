"""Application boundary for local clinical sync transactions."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from icu_patient_tracker.persistence.sync_repository import SyncConflict, SyncOperation
from icu_patient_tracker.persistence.unit_of_work import SqlAlchemyUnitOfWork
from icu_patient_tracker.sync.contracts import ChangePage, PushResult

__all__ = ["ClinicalSyncService", "SyncConflict"]


class ClinicalSyncService:
    def __init__(self, factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
        self.factory = factory

    def initialize(self, name: str, device_id: UUID, workspace_id: UUID) -> None:
        with self.factory() as unit:
            state = unit.sync.state()
            if state is not None and (
                state.device_id != device_id or state.workspace_id not in (None, workspace_id)
            ):
                raise ValueError(
                    "This database is paired to another device. Use a separate local database."
                )
            unit.sync.ensure_device(name, device_id=device_id)
            unit.sync.update_state(status="offline", workspace_id=workspace_id)
            unit.clinical_sync.seed()

    def prepare(self, device_id: UUID) -> tuple[tuple[SyncOperation, ...], int]:
        with self.factory() as unit:
            state = unit.sync.state()
            if state is None or state.device_id != device_id:
                raise ValueError("This database has not been paired to this device.")
            return unit.clinical_sync.prepare(), unit.sync.device(device_id).last_pull_sequence

    def finish(
        self,
        operations: tuple[SyncOperation, ...],
        results: tuple[PushResult, ...],
        page: ChangePage,
        device_id: UUID,
    ) -> tuple[bool, int, int]:
        with self.factory() as unit:
            unit.clinical_sync.accept_push(operations, results)
            changed = unit.clinical_sync.apply_page(page, device_id)
            queued, conflicts = unit.clinical_sync.summary()
            unit.sync.update_state(
                status="conflict"
                if conflicts
                else "syncing"
                if queued or page.has_more
                else "synced",
                last_pull_at=datetime.now(UTC),
            )
            return changed, queued, conflicts

    def selection(
        self, patient_id: UUID | None, day_id: UUID | None
    ) -> tuple[UUID | None, UUID | None]:
        with self.factory() as unit:
            if patient_id is None or not unit.patients.exists(patient_id):
                return None, None
            patient = unit.patients.get(patient_id)
            if day_id not in {day.id for day in patient.hospital_days}:
                day_id = patient.hospital_days[-1].id if patient.hospital_days else None
            return patient_id, day_id

    def conflicts(self) -> tuple[SyncConflict, ...]:
        with self.factory() as unit:
            return unit.sync.unresolved_conflicts()

    def local_version(self, patient_id: UUID) -> tuple[dict[str, object], int]:
        with self.factory() as unit:
            return unit.clinical_sync.local_version(patient_id)

    def resolve(self, conflict: SyncConflict, local_choice: bool, revision: int) -> None:
        with self.factory() as unit:
            unit.clinical_sync.resolve(conflict, keep_local=local_choice, local_revision=revision)
