"""Nested Qt event processing must not re-enter a persistence operation."""

from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from icu_patient_tracker.services.exceptions import AutosaveServiceError
from icu_patient_tracker.ui.autosave_adapter import QtAutosaveAdapter


def test_poll_stays_guarded_while_save_processes_events():
    application = QApplication.instance() or QApplication([])
    coordinator = Mock()
    adapter = QtAutosaveAdapter(coordinator)

    def save():
        if coordinator.poll.call_count == 1:
            adapter._poll()
            application.processEvents()
        return False

    coordinator.poll.side_effect = save
    adapter._poll()
    application.processEvents()
    assert coordinator.poll.call_count == 1
    adapter._poll()
    application.processEvents()
    assert coordinator.poll.call_count == 2


def test_failure_callback_cannot_schedule_another_save():
    application = QApplication.instance() or QApplication([])
    coordinator = Mock()
    coordinator.poll.side_effect = AutosaveServiceError("Synthetic save failure")
    adapter = QtAutosaveAdapter(coordinator)
    failures = []

    def failed(message):
        failures.append(message)
        adapter._poll()
        application.processEvents()

    adapter.failure.connect(failed)
    adapter._poll()
    application.processEvents()
    application.processEvents()
    assert coordinator.poll.call_count == 1
    assert failures == ["Synthetic save failure"]
    assert not adapter.is_active


def test_stopping_during_save_does_not_report_a_late_failure():
    application = QApplication.instance() or QApplication([])
    coordinator = Mock()
    adapter = QtAutosaveAdapter(coordinator)
    failures = []
    adapter.failure.connect(failures.append)

    def save():
        adapter.stop()
        raise AutosaveServiceError("Synthetic failure during shutdown")

    coordinator.poll.side_effect = save
    adapter._poll()
    application.processEvents()
    assert coordinator.poll.call_count == 1
    assert failures == []
