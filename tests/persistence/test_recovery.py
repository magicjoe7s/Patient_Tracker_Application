"""Atomic and conflict-aware unsaved-editor recovery tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from icu_patient_tracker.persistence.exceptions import RecoveryError
from icu_patient_tracker.persistence.recovery import RecoveryEntry, RecoverySnapshot, RecoveryStore
from icu_patient_tracker.services.exceptions import RecoveryServiceError
from icu_patient_tracker.services.recovery_service import RecoveryService


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_recovery_store_round_trips_and_archives_cleared_snapshot(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path / "recovery.json")
    snapshot = RecoverySnapshot(
        uuid4(),
        uuid4(),
        datetime(2026, 7, 22, 12, tzinfo=UTC),
        (RecoveryEntry("soap", "fingerprint", {"markdown_text": "unsaved"}),),
    )

    store.write(snapshot)
    assert store.load() == snapshot
    archived = store.clear()

    assert archived == tmp_path / "recovery.json.bak"
    assert archived is not None and archived.exists()
    assert store.load() is None


def test_invalid_recovery_snapshot_is_never_best_effort_loaded(tmp_path: Path) -> None:
    path = tmp_path / "recovery.json"
    path.write_text('{"version": 99}', encoding="utf-8")

    with pytest.raises(RecoveryError):
        RecoveryStore(path).load()


def test_recovery_service_debounces_and_detects_canonical_conflicts(tmp_path: Path) -> None:
    clock = FakeClock()
    store = RecoveryStore(tmp_path / "recovery.json")
    service = RecoveryService(
        store,
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=UTC),
        monotonic=clock,
        debounce_seconds=0.9,
    )
    patient_id = uuid4()
    day_id = uuid4()
    service.stage(
        key="charting",
        patient_id=patient_id,
        hospital_day_id=day_id,
        base_values={"assessment": "saved"},
        draft_values={"assessment": "unsaved"},
    )

    clock.value = 0.8
    assert not service.poll()
    clock.value = 0.9
    assert service.poll()
    snapshot = service.available()
    assert snapshot is not None
    assert snapshot.entries[0].values == {"assessment": "unsaved"}
    assert service.conflicting_entries(snapshot, {"charting": {"assessment": "saved"}}) == ()
    assert service.conflicting_entries(
        snapshot, {"charting": {"assessment": "newer committed value"}}
    ) == ("charting",)


def test_failed_recovery_write_remains_retryable(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocked", encoding="utf-8")
    service = RecoveryService(
        RecoveryStore(blocked_parent / "recovery.json"),
        debounce_seconds=0,
    )
    service.stage(
        key="sandbox",
        patient_id=uuid4(),
        hospital_day_id=uuid4(),
        base_values={"markdown_text": ""},
        draft_values={"markdown_text": "recover me"},
    )

    with pytest.raises(RecoveryServiceError):
        service.flush()
    with pytest.raises(RecoveryServiceError):
        service.flush()


def test_recovery_values_are_not_materialized_until_idle_flush(tmp_path: Path) -> None:
    clock = FakeClock()
    calls: list[str] = []
    service = RecoveryService(
        RecoveryStore(tmp_path / "recovery.json"),
        monotonic=clock,
        debounce_seconds=2,
    )
    service.stage(
        key="soap",
        patient_id=uuid4(),
        hospital_day_id=uuid4(),
        base_values=lambda: calls.append("base") or {"markdown": "saved"},
        draft_values=lambda: calls.append("draft") or {"markdown": "typed"},
    )

    assert calls == []
    clock.value = 1.9
    assert not service.poll()
    assert calls == []
    clock.value = 2.0
    assert service.poll()
    assert calls == ["base", "draft"]
