"""Independent local databases converge without discarding concurrent edits."""

from uuid import uuid4

from icu_patient_tracker.persistence.clinical_payload import encode_patient
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.clinical_sync_service import ClinicalSyncService
from icu_patient_tracker.sync.contracts import ChangePage, PushResult, ServerChange
from tests.persistence.factories import make_representative_patient


def test_three_databases_offline_conflict_retry_and_delete(tmp_path):
    databases = [DatabaseManager(tmp_path / f"device-{n}.sqlite3") for n in range(3)]
    devices = [uuid4() for _ in databases]
    workspace = uuid4()
    services = [ClinicalSyncService(db.unit_of_work) for db in databases]
    changes = []
    receipts = {}

    def exchange(index, lose_response=False):
        operations, cursor = services[index].prepare(devices[index])
        results = []
        for op in operations:
            if op.operation_id not in receipts:
                latest = next(
                    (c for c in reversed(changes) if c.entity_id == str(op.entity_id)), None
                )
                version = latest.server_version if latest else 0
                accepted = version == op.base_server_version
                if accepted:
                    version += 1
                    changes.append(
                        ServerChange(
                            len(changes) + 1,
                            op.entity_type,
                            str(op.entity_id),
                            op.operation,
                            version,
                            op.payload,
                        )
                    )
                receipts[op.operation_id] = PushResult(
                    str(op.operation_id),
                    "accepted" if accepted else "conflict",
                    op.entity_type,
                    str(op.entity_id),
                    version,
                    len(changes) if accepted else None,
                    op.payload if accepted else latest.payload,
                )
            results.append(receipts[op.operation_id])
        if not lose_response:
            services[index].finish(
                operations,
                tuple(results),
                ChangePage(tuple(c for c in changes if c.sequence > cursor), len(changes), False),
                devices[index],
            )

    try:
        for index, db in enumerate(databases):
            db.initialize()
            services[index].initialize(f"Test {index}", devices[index], workspace)
        patient = make_representative_patient()
        with databases[0].unit_of_work() as unit:
            unit.patients.add(patient)
        exchange(0, lose_response=True)
        exchange(0)
        assert len(changes) == 1
        exchange(1)
        exchange(2)
        for db in databases:
            with db.unit_of_work() as unit:
                assert encode_patient(unit.patients.get(patient.id)) == encode_patient(patient)
        for index in (0, 1):
            with databases[index].unit_of_work() as unit:
                edited = unit.patients.get(patient.id)
                edited.one_line_summary = f"Offline note {index}"
                unit.patients.save(edited)
        exchange(0)
        exchange(1)
        (conflict,) = services[1].conflicts()
        with databases[1].unit_of_work() as unit:
            assert unit.patients.get(patient.id).one_line_summary == "Offline note 1"
        _, revision = services[1].local_version(patient.id)
        services[1].resolve(conflict, False, revision)
        exchange(2)
        for db in databases:
            with db.unit_of_work() as unit:
                assert unit.patients.get(patient.id).one_line_summary == "Offline note 0"
        with databases[2].unit_of_work() as unit:
            unit.patients.delete(patient.id)
        exchange(2)
        exchange(0)
        exchange(1)
        for db in databases:
            with db.unit_of_work() as unit:
                assert not unit.patients.exists(patient.id)
                assert unit.clinical_sync.summary() == (0, 0)
    finally:
        for db in databases:
            db.dispose()
