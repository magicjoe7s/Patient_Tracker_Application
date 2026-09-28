"""Loss-prevention tests for patient snapshot reconciliation."""

from uuid import uuid4

import pytest

from icu_patient_tracker.persistence.clinical_payload import decode_patient, encode_patient
from icu_patient_tracker.sync.contracts import ChangePage, PushResult, ServerChange
from tests.persistence.factories import make_representative_patient


def accept(operation, version=1):
    return PushResult(
        str(operation.operation_id),
        "accepted",
        operation.entity_type,
        str(operation.entity_id),
        version,
        version,
        operation.payload,
    )


def test_all_clinical_fields_roundtrip():
    patient = make_representative_patient()
    payload = encode_patient(patient)
    assert encode_patient(decode_patient(payload, patient.id)) == payload


def test_local_capture_rolls_back_with_patient(database_manager):
    patient = make_representative_patient()
    with pytest.raises(RuntimeError), database_manager.unit_of_work() as unit:
        unit.patients.add(patient)
        raise RuntimeError("simulated failure")
    with database_manager.unit_of_work() as unit:
        assert unit.clinical_sync.summary() == (0, 0)
        assert not unit.patients.exists(patient.id)


def test_edit_during_network_roundtrip_remains_pending(database_manager):
    patient = make_representative_patient()
    with database_manager.unit_of_work() as unit:
        unit.patients.add(patient)
        operations = unit.clinical_sync.prepare()
    patient.one_line_summary = "Edited while network request was in flight"
    with database_manager.unit_of_work() as unit:
        unit.patients.save(patient)
        assert unit.clinical_sync.prepare() == operations
        unit.clinical_sync.accept_push(operations, (accept(operations[0]),))
    with database_manager.unit_of_work() as unit:
        newer = unit.clinical_sync.prepare()
        assert newer[0].base_server_version == 1
        assert newer[0].operation_id != operations[0].operation_id
        assert (
            decode_patient(newer[0].payload, patient.id).one_line_summary
            == patient.one_line_summary
        )


def test_remote_edits_preserve_local_and_resolve_then_retry(database_manager):
    patient = make_representative_patient()
    with database_manager.unit_of_work() as unit:
        unit.patients.add(patient)
        device = unit.sync.ensure_device("Test")
        unit.sync.update_state(status="offline", workspace_id=uuid4())
    remote = make_representative_patient(mrn=None)
    remote.id = patient.id
    # Use a valid graph of the same patient, only change a patient-level field.
    remote = decode_patient(encode_patient(patient), patient.id)
    remote.one_line_summary = "Remote version"
    change = ServerChange(
        1, "patient_snapshot_v1", str(patient.id), "upsert", 1, encode_patient(remote)
    )
    with database_manager.unit_of_work() as unit:
        assert not unit.clinical_sync.apply_page(ChangePage((change,), 1, False), device.id)
        assert unit.patients.get(patient.id).one_line_summary == ""
        conflicts = unit.sync.unresolved_conflicts()
        assert len(conflicts) == 1
        assert unit.clinical_sync.prepare() == ()
        _, revision = unit.clinical_sync.local_version(patient.id)
        unit.clinical_sync.resolve(conflicts[0], keep_local=True, local_revision=revision)
        operations = unit.clinical_sync.prepare()
        assert operations[0].base_server_version == 1
        unit.clinical_sync.accept_push(operations, (accept(operations[0], 2),))
        assert unit.clinical_sync.summary() == (0, 0)


def test_pull_creates_patient_without_echo_and_propagates_delete(database_manager):
    patient = make_representative_patient()
    with database_manager.unit_of_work() as unit:
        device = unit.sync.ensure_device("Test")
        changes = (
            ServerChange(
                1, "patient_snapshot_v1", str(patient.id), "upsert", 1, encode_patient(patient)
            ),
        )
        assert unit.clinical_sync.apply_page(ChangePage(changes, 1, False), device.id)
        assert unit.clinical_sync.summary() == (0, 0)
        assert unit.clinical_sync.prepare() == ()
        deletion = ServerChange(
            2, "patient_snapshot_v1", str(patient.id), "delete", 2, encode_patient(None)
        )
        assert unit.clinical_sync.apply_page(ChangePage((deletion,), 2, False), device.id)
        assert not unit.patients.exists(patient.id)
        assert unit.clinical_sync.prepare() == ()


def test_newer_payload_version_rejected():
    with pytest.raises(ValueError, match="newer app"):
        decode_patient({"schema_version": 2, "patient": None}, uuid4())
