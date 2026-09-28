"""Capture latest local patient revision within the patient's existing transaction."""

from uuid import UUID

from sqlalchemy.orm import Session

from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.clinical_payload import dump_payload, encode_patient
from icu_patient_tracker.persistence.orm_models import ClinicalSyncRecord


def capture(session: Session, patient_id: UUID, patient: Patient | None) -> None:
    if session.info.get("applying_remote_sync"):
        return
    payload = dump_payload(encode_patient(patient))
    record = session.get(ClinicalSyncRecord, patient_id)
    if record is None:
        session.add(
            ClinicalSyncRecord(
                patient_id=patient_id,
                payload_json=payload,
                local_revision=1,
                synced_revision=0,
                server_version=0,
                operation_id=None,
                operation_revision=None,
            )
        )
    elif record.payload_json != payload:
        record.payload_json = payload
        record.local_revision += 1
    session.flush()
