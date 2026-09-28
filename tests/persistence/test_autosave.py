"""Deterministic debounce, flush, failure, retry, and shutdown tests."""

import pytest

from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.autosave import AutosaveController
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.exceptions import AutosaveError


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_dirty_state_debounces_and_coalesces_rapid_changes() -> None:
    clock = FakeClock()
    saves: list[str] = []
    controller = AutosaveController(
        lambda: saves.append("saved"), clock=clock, debounce_seconds=0.7
    )

    controller.mark_dirty()
    first_deadline = controller.deadline
    clock.advance(0.5)
    controller.mark_dirty()
    assert controller.deadline is not None
    assert first_deadline is not None
    assert controller.deadline > first_deadline
    clock.advance(0.6)
    assert not controller.poll()
    clock.advance(0.1)
    assert controller.poll()
    assert saves == ["saved"]
    assert not controller.is_dirty


def test_save_now_and_shutdown_flush_pending_work() -> None:
    saves: list[str] = []
    controller = AutosaveController(lambda: saves.append("saved"))
    controller.mark_dirty()
    assert controller.save_now()
    controller.mark_dirty()
    assert controller.shutdown()
    assert saves == ["saved", "saved"]


def test_failed_save_retains_dirty_state_and_requires_explicit_retry() -> None:
    clock = FakeClock()
    attempts = 0

    def save() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("database unavailable")

    controller = AutosaveController(save, clock=clock, retry_seconds=2)
    controller.mark_dirty()
    with pytest.raises(AutosaveError):
        controller.save_now()
    assert controller.is_dirty
    assert controller.is_paused
    assert controller.last_error is not None
    assert not controller.poll()

    controller.schedule_retry()
    clock.advance(2)
    assert controller.poll()
    assert not controller.is_dirty
    assert controller.last_error is None


def test_failed_transaction_does_not_clear_autosave_dirty_state(
    database_manager: DatabaseManager,
) -> None:
    patient = Patient("Bella", "Canine", mrn="123456")

    def failed_transaction() -> None:
        with database_manager.unit_of_work() as unit_of_work:
            unit_of_work.patients.add(patient)
            raise RuntimeError("simulated later failure")

    controller = AutosaveController(failed_transaction)
    controller.mark_dirty()
    with pytest.raises(AutosaveError):
        controller.save_now()
    with database_manager.unit_of_work() as unit_of_work:
        assert not unit_of_work.patients.exists(patient.id)
    assert controller.is_dirty
