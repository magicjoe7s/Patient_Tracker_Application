"""Patient snapshot reconciliation and explicit conflict resolution."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from icu_patient_tracker.persistence.clinical_capture import capture
from icu_patient_tracker.persistence.clinical_payload import decode_patient, dump_payload
from icu_patient_tracker.persistence.orm_models import ClinicalSyncRecord, SyncConflictRecord
from icu_patient_tracker.persistence.sqlalchemy_patient_repository import (
    SqlAlchemyPatientRepository,
)
from icu_patient_tracker.persistence.sync_repository import (
    SqlAlchemySyncRepository,
    SyncConflict,
    SyncOperation,
)
from icu_patient_tracker.sync.contracts import ChangePage, PushResult, ServerChange

ENTITY_TYPE = "patient_snapshot_v1"


class ClinicalSyncRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.sync = SqlAlchemySyncRepository(session)
        self.patients = SqlAlchemyPatientRepository(session)

    def seed(self) -> None:
        """Capture pre-sync patients once; never reset a previously synced revision."""
        for patient in self.patients.list():
            if self.session.get(ClinicalSyncRecord, patient.id) is None:
                capture(self.session, patient.id, patient)

    def prepare(self) -> tuple[SyncOperation, ...]:
        """Freeze operations until acknowledged; later edits keep a newer revision."""
        blocked = {c.entity_id for c in self.sync.unresolved_conflicts()}
        dirty = self.session.scalars(
            select(ClinicalSyncRecord)
            .where(ClinicalSyncRecord.local_revision > ClinicalSyncRecord.synced_revision)
            .order_by(ClinicalSyncRecord.patient_id)
        ).all()
        operations: list[SyncOperation] = []
        byte_count = 0
        for record in dirty:
            if record.patient_id in blocked:
                continue
            operation = self._operation(record)
            size = len(dump_payload(operation.payload).encode()) + 512
            if size > 900_000:
                raise ValueError("A patient record is too large for sync; local data is saved.")
            if operations and (byte_count + size > 900_000 or len(operations) >= 50):
                break
            operations.append(operation)
            byte_count += size
        return tuple(operations)

    def _operation(self, record: ClinicalSyncRecord) -> SyncOperation:
        if record.operation_id is not None:
            return self.sync.operation(record.operation_id)
        payload = json.loads(record.payload_json)
        operation = self.sync.queue(
            entity_type=ENTITY_TYPE,
            entity_id=record.patient_id,
            operation="delete" if payload["patient"] is None else "upsert",
            base_server_version=record.server_version,
            payload=payload,
        )
        record.operation_id = operation.operation_id
        record.operation_revision = record.local_revision
        self.session.flush()
        return operation

    def accept_push(
        self, operations: tuple[SyncOperation, ...], results: tuple[PushResult, ...]
    ) -> None:
        expected = {str(op.operation_id): op for op in operations}
        if len(results) != len(expected) or {r.operation_id for r in results} != set(expected):
            raise ValueError("Sync server returned unexpected operation receipts.")
        for result in results:
            operation = expected[result.operation_id]
            if (result.entity_type, result.entity_id) != (ENTITY_TYPE, str(operation.entity_id)):
                raise ValueError("Sync server returned an unexpected patient identity.")
            record = self._record(operation.entity_id)
            if record.operation_id != operation.operation_id:
                raise ValueError("Local sync receipt no longer matches the pending operation.")
            decode_patient(result.server_payload, record.patient_id)
            if result.status == "accepted":
                if (
                    result.server_version != operation.base_server_version + 1
                    or result.server_payload != operation.payload
                ):
                    raise ValueError("Sync server returned an invalid accepted version.")
                record.server_version = result.server_version
                record.synced_revision = record.operation_revision or 0
                record.operation_id = None
                record.operation_revision = None
                self.sync.acknowledge(operation.operation_id)
            else:
                self._conflict(record, result.server_payload, result.server_version)
        self.session.flush()

    def apply_page(self, page: ChangePage, device_id: UUID) -> bool:
        changed = False
        for change in page.changes:
            if change.entity_type == "synthetic_patient":
                continue
            if change.entity_type != ENTITY_TYPE:
                raise ValueError("A newer app is required for this server record type.")
            changed = self._apply(change) or changed
        self.sync.advance_pull_cursor(device_id, page.next_cursor)
        return changed

    def _apply(self, change: ServerChange) -> bool:
        patient_id = UUID(change.entity_id)
        patient = decode_patient(change.payload, patient_id)
        if (change.operation == "delete") != (patient is None):
            raise ValueError("Sync deletion does not match its payload.")
        record = self.session.get(ClinicalSyncRecord, patient_id)
        if record is not None and change.server_version <= record.server_version:
            return False
        if record is not None and (
            record.local_revision > record.synced_revision or record.operation_id is not None
        ):
            self._conflict(record, change.payload, change.server_version)
            return False
        self._write_patient(patient_id, change.payload)
        if record is None:
            record = ClinicalSyncRecord(
                patient_id=patient_id,
                local_revision=0,
                synced_revision=0,
                server_version=0,
                payload_json="",
                operation_id=None,
                operation_revision=None,
            )
            self.session.add(record)
        record.payload_json = dump_payload(change.payload)
        record.server_version = change.server_version
        record.local_revision += 1
        record.synced_revision = record.local_revision
        self.session.flush()
        return True

    def _conflict(
        self, record: ClinicalSyncRecord, payload: dict[str, object], version: int
    ) -> None:
        operation = self._operation(record)
        existing = self.session.scalar(
            select(SyncConflictRecord).where(
                SyncConflictRecord.operation_id == operation.operation_id,
                SyncConflictRecord.resolution.is_(None),
            )
        )
        if existing is None:
            self.sync.record_conflict(
                operation.operation_id, server_payload=payload, server_version=version
            )
        elif version > existing.server_version:
            existing.server_payload_json = dump_payload(payload)
            existing.server_version = version

    def resolve(self, conflict: SyncConflict, *, keep_local: bool, local_revision: int) -> None:
        record = self._record(conflict.entity_id)
        current = next((c for c in self.sync.unresolved_conflicts() if c.id == conflict.id), None)
        if (
            current is None
            or record.local_revision != local_revision
            or current.server_version != conflict.server_version
        ):
            raise ValueError("This conflict changed. Reopen it to review the latest versions.")
        history = self.session.get(SyncConflictRecord, current.id)
        if history is not None:
            history.local_payload_json = record.payload_json
        if not keep_local:
            self._write_patient(record.patient_id, current.server_payload)
            record.payload_json = dump_payload(current.server_payload)
        record.server_version = current.server_version
        record.local_revision += 1
        record.synced_revision = record.local_revision - 1 if keep_local else record.local_revision
        record.operation_id = None
        record.operation_revision = None
        # Retain the old outbox and both conflict payloads as a review history.
        self.sync.resolve_conflict(
            current.id, resolution="keep_local" if keep_local else "keep_server"
        )
        self.session.flush()

    def local_version(self, patient_id: UUID) -> tuple[dict[str, object], int]:
        record = self._record(patient_id)
        return json.loads(record.payload_json), record.local_revision

    def summary(self) -> tuple[int, int]:
        dirty = self.session.scalars(
            select(ClinicalSyncRecord.patient_id).where(
                ClinicalSyncRecord.local_revision > ClinicalSyncRecord.synced_revision
            )
        ).all()
        return len(dirty), len(self.sync.unresolved_conflicts())

    def _record(self, patient_id: UUID) -> ClinicalSyncRecord:
        record = self.session.get(ClinicalSyncRecord, patient_id)
        if record is None:
            raise ValueError("Local sync revision was not found.")
        return record

    def _write_patient(self, patient_id: UUID, payload: dict[str, object]) -> None:
        patient = decode_patient(payload, patient_id)
        self.session.info["applying_remote_sync"] = True
        try:
            exists = self.patients.exists(patient_id)
            if patient is None and exists:
                self.patients.delete(patient_id)
            elif patient is not None:
                if exists:
                    self.patients.save(patient)
                else:
                    self.patients.add(patient)
        finally:
            self.session.info.pop("applying_remote_sync", None)
