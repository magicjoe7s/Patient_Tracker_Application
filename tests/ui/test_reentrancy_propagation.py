"""Repeat real UI entry points during nested callbacks and shutdown."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QMessageBox

from icu_patient_tracker.dialogs.new_patient_dialog import NewPatientDialog
from icu_patient_tracker.dialogs.settings_dialog import SettingsDialog
from icu_patient_tracker.domain.enums import TaskCategory
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.services.reminder_service import HourlyDigest
from icu_patient_tracker.ui import sync_adapter
from icu_patient_tracker.ui.main_window import MainWindow
from icu_patient_tracker.ui.reminder_adapter import QtReminderAdapter
from tests.ui.test_main_window import make_runtime
from tests.ui.test_window_loop_regressions import runtime as runtime


@pytest.mark.parametrize(
    "action", ["settings", "patient", "task", "board", "problem", "dx", "sync"]
)
def test_repeated_modal_action_opens_once_and_can_be_reopened(runtime, monkeypatch, action):
    if action == "settings":
        invoke = runtime.window._show_settings
    elif action == "patient":
        invoke = runtime.window.patient_panel.prompt_create
    elif action == "task":
        invoke = runtime.window.workspace.tasks._prompt_add
    elif action == "problem":
        invoke = runtime.window.workspace.problems._prompt_add
    elif action == "dx":
        runtime.window._show_pending_diagnostics()
        invoke = runtime.window._pending_diagnostics_dialog._add
    elif action == "sync":
        invoke = runtime.sync.show_settings
    else:
        runtime.window._show_task_board()
        invoke = next(iter(runtime.window._task_board_dialog.panes.values()))._add
    dialogs = []

    def execute(dialog):
        dialogs.append(dialog)
        if len(dialogs) == 1:
            invoke()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", execute)
    # NewPatientDialog inherits QDialog.exec without replacing it.
    assert issubclass(NewPatientDialog, QDialog)
    invoke()
    assert len(dialogs) == 1
    invoke()
    assert len(dialogs) == 2


def test_modal_action_can_be_retried_after_an_exception(runtime, monkeypatch):
    calls = []

    def execute(dialog):
        calls.append(dialog)
        if len(calls) == 1:
            raise RuntimeError("Synthetic dialog failure")
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(SettingsDialog, "exec", execute)
    with pytest.raises(RuntimeError, match="Synthetic dialog failure"):
        runtime.window._show_settings()
    runtime.window._show_settings()
    assert len(calls) == 2


def test_real_task_board_button_still_opens_one_editor(runtime, monkeypatch):
    runtime.window._show_task_board()
    pane = next(iter(runtime.window._task_board_dialog.panes.values()))
    calls = []

    def execute(dialog):
        calls.append(dialog)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", execute)
    pane.add_button.click()
    assert len(calls) == 1


def test_device_prompt_does_not_reenter_from_another_toggle(runtime, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic device prompt patient", species="Canine"
    )
    panel = runtime.window.workspace.instrumentation
    label = next(iter(panel.checkboxes))
    calls = []

    def enter(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            panel._device_toggled(label, True)
        return "", False

    monkeypatch.setattr(QInputDialog, "getText", enter)
    panel._device_toggled(label, True)
    assert len(calls) == 1
    assert not panel.checkboxes[label].isChecked()
    assert runtime.controller.devices() == ()


def test_reminder_notification_cannot_start_an_overlapping_poll(runtime):
    now = datetime(2026, 10, 20, 10, tzinfo=UTC)
    service = Mock()
    service.due.return_value = (Reminder(uuid4(), uuid4(), uuid4(), now, "Synthetic task"),)
    service.hourly_digest.return_value = HourlyDigest(now, (), (), (), (), 0, 0)
    sink = Mock()
    adapter = QtReminderAdapter(service, notification_sink=sink, now=lambda: now)

    def show(*args):
        if sink.show.call_count == 1:
            adapter.poll()
        return True

    sink.show.side_effect = show
    adapter.poll()
    assert service.due.call_count == 1
    assert service.mark_shown.call_count == 1
    assert sink.show.call_count == 1


def test_snooze_during_digest_delivery_survives_callback_return(runtime):
    clock = [datetime(2026, 10, 20, 10, tzinfo=UTC)]
    service = Mock()
    service.due.return_value = ()
    digest = HourlyDigest(clock[0], (), (), (), (), 1, 0)
    service.hourly_digest.return_value = digest
    adapter = QtReminderAdapter(service, notification_sink=Mock(), now=lambda: clock[0])
    received = []

    def receive(value):
        received.append(value)
        if len(received) == 1:
            adapter.snooze_digest()
            adapter.poll()

    adapter.digest_ready.connect(receive)
    adapter.poll()
    assert received == [digest]
    clock[0] += timedelta(minutes=4)
    adapter.poll()
    assert received == [digest]
    clock[0] += timedelta(minutes=1)
    adapter.poll()
    assert received == [digest, digest]


def test_reminder_failure_does_not_repeat_until_service_recovers(runtime):
    service = Mock()
    service.due.side_effect = RuntimeError("Synthetic reminder outage")
    adapter = QtReminderAdapter(service, notification_sink=Mock())
    failures = []
    adapter.failure.connect(failures.append)
    for _ in range(10):
        adapter.poll()
    assert failures == ["Synthetic reminder outage"]
    service.due.side_effect = None
    service.due.return_value = ()
    adapter.poll()
    service.due.side_effect = RuntimeError("Synthetic reminder outage")
    adapter.poll()
    assert failures == ["Synthetic reminder outage", "Synthetic reminder outage"]


def test_stopping_during_reminder_delivery_prevents_digest_and_timer_restart(runtime):
    now = datetime(2026, 10, 20, 10, tzinfo=UTC)
    service = Mock()
    service.due.return_value = (Reminder(uuid4(), uuid4(), uuid4(), now, "Synthetic task"),)
    sink = Mock()
    adapter = QtReminderAdapter(service, notification_sink=sink, now=lambda: now)
    received = []
    adapter.digest_ready.connect(received.append)
    sink.show.side_effect = lambda *args: adapter.stop()
    adapter.start()
    adapter.poll()
    assert not adapter._timer.isActive()
    assert received == []
    assert service.hourly_digest.call_count == 0


class FakeNetworkJob(QObject):
    result_ready = Signal(object)
    failed = Signal(str)
    finished = Signal()
    created: ClassVar[list["FakeNetworkJob"]] = []

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.created.append(self)

    def start(self):
        pass

    def wait(self):
        return True


def test_sync_jobs_are_serialized_and_stale_callbacks_are_ignored(runtime, monkeypatch):
    monkeypatch.setattr(sync_adapter, "_NetworkJob", FakeNetworkJob)
    adapter = runtime.sync
    results = []
    FakeNetworkJob.created.clear()
    adapter._start_job(lambda: "first", results.append)
    first = adapter.job
    adapter._start_job(lambda: "overlap", results.append)
    assert adapter.job is first
    assert len(FakeNetworkJob.created) == 1
    first.result_ready.emit("first result")
    first.finished.emit()
    adapter._start_job(lambda: "second", results.append)
    second = adapter.job
    first.result_ready.emit("stale result")
    first.failed.emit("stale error")
    adapter._job_finished(first)
    assert adapter.job is second
    second.result_ready.emit("second result")
    second.finished.emit()
    assert results == ["first result", "second result"]
    assert adapter.job is None


def test_sync_busy_and_stopped_actions_do_not_open_message_boxes(runtime, monkeypatch):
    monkeypatch.setattr(sync_adapter, "_NetworkJob", FakeNetworkJob)
    adapter = runtime.sync

    def blocking_notice(*args, **kwargs):
        pytest.fail("A busy sync action opened a blocking notice")

    monkeypatch.setattr(QMessageBox, "information", blocking_notice)
    adapter._start_job(lambda: None, lambda result: None)
    current = adapter.job
    for _ in range(5):
        adapter.show_settings()
    assert "finishing" in runtime.window.statusBar().currentMessage()
    assert adapter.job is current
    adapter.stop()
    before = adapter.button.text()
    current.failed.emit("Late failure")
    current.result_ready.emit("Late result")
    current.finished.emit()
    calls = []

    def execute(dialog):
        calls.append(dialog)
        pytest.fail("Dialog reopened after stop")

    monkeypatch.setattr(QDialog, "exec", execute)
    adapter.show_settings()
    adapter.review_conflicts()
    adapter._start_job(lambda: None, lambda result: None)
    assert adapter.button.text() == before
    assert adapter.job is None
    assert calls == []


def test_stopping_autosave_cancels_a_queued_save(runtime, monkeypatch):
    coordinator = runtime.autosave._coordinator
    poll = Mock(return_value=False)
    due = Mock(return_value=True)
    monkeypatch.setattr(coordinator, "poll", poll)
    monkeypatch.setattr(coordinator, "is_due", due, raising=False)
    runtime.autosave._poll()
    runtime.autosave.stop()
    runtime.application.processEvents()
    assert due.call_count == 0
    assert poll.call_count == 0


def test_stopped_autosave_ignores_a_late_worker_failure(runtime):
    if not hasattr(runtime.autosave, "_save_failed"):
        pytest.skip("The release adapter saves synchronously; it has no late worker signal")
    failures = []
    runtime.autosave.failure.connect(failures.append)
    runtime.autosave.stop()
    runtime.autosave._save_failed("Late synthetic save error")
    runtime.application.processEvents()
    assert failures == []
    assert runtime.window._error_dialog is None


def test_shutdown_cancels_queued_chart_refreshes(runtime, monkeypatch):
    refresh = Mock(wraps=runtime.window.workspace.patient_summary.refresh)
    monkeypatch.setattr(runtime.window.workspace.patient_summary, "refresh", refresh)
    runtime.events.soap_changed.emit("", "markdown_refreshed")
    runtime.events.soap_changed.emit("", "markdown_refreshed")
    assert runtime.shutdown()
    refresh.reset_mock()
    runtime.application.processEvents()
    assert refresh.call_count == 0


def test_shutdown_before_first_event_does_not_offer_recovery(tmp_path, monkeypatch):
    calls = []

    def offer(window):
        calls.append(window)

    monkeypatch.setattr(MainWindow, "_offer_recovery", offer)
    result = make_runtime(tmp_path)
    assert result.shutdown()
    result.application.processEvents()
    assert calls == []


def test_exit_from_diagnostic_capture_does_not_reopen_task_board(runtime):
    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic shutdown patient", species="Canine"
    )
    context = runtime.controller.context
    task = runtime.controller.services.tasks.create(
        context.patient_id,
        context.hospital_day_id,
        title="Synthetic diagnostic",
        category=TaskCategory.DIAGNOSTIC,
    )
    runtime.window._show_task_board()
    board = runtime.window._task_board_dialog
    board.refresh()
    row = board.panes[TaskCategory.DIAGNOSTIC]._rows[task.id]
    runtime.window._show_diagnostic_result_for_board_row(row)
    capture = runtime.window._diagnostic_result_dialog
    assert capture.isVisible()
    assert runtime.shutdown()
    runtime.application.processEvents()
    assert not capture.isVisible()
    assert not board.isVisible()
    assert not runtime.window.isVisible()


def test_late_return_and_error_signals_do_not_reopen_closed_workspace(runtime):
    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic late-callback patient", species="Canine"
    )
    runtime.window._show_diagnostic_text_editor()
    editor = runtime.window._diagnostic_text_dialog
    assert editor.isVisible()
    assert runtime.shutdown()
    assert not editor.isVisible()
    runtime.controller.error_raised.emit("Late failure", "Arrived after shutdown")
    runtime.events.soap_changed.emit("", "markdown_refreshed")
    runtime.window._return_from_patient_popup()
    runtime.window._return_from_task_board()
    runtime.window._return_from_diagnostic_text_editor()
    runtime.window.activate_main_window()
    runtime.application.processEvents()
    assert runtime.window._error_dialog is None
    assert not runtime.window.isVisible()
