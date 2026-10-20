"""Exercise task-filter clicks and repeated failures with real Qt windows."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.enums import TaskCategory
from icu_patient_tracker.services.exceptions import RecoveryServiceError, SettingsValidationError
from icu_patient_tracker.ui.recovery_adapter import QtRecoveryAdapter


@pytest.fixture
def runtime(tmp_path: Path):
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=60,
        )
    )
    result = create_runtime(["icu-patient-tracker"], config_path)
    result.window.show()
    result.application.processEvents()
    try:
        yield result
    finally:
        result.shutdown()


def _board(runtime):
    runtime.window._show_task_board()
    board = runtime.window._task_board_dialog
    assert board is not None
    # Both synchronous release and asynchronous development board loaders apply
    # this authoritative snapshot before testing the user's filter click.
    board.refresh()
    return board


def test_hide_completed_keeps_windows_stable_and_preferences_synchronized(runtime, monkeypatch):
    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic regression patient", species="Canine"
    )
    context = runtime.controller.context
    service = runtime.controller.services.tasks
    task = service.create(context.patient_id, context.hospital_day_id, title="Completed task")
    service.complete(context.patient_id, task.id)
    board = _board(runtime)
    pane = board.panes[TaskCategory.CLINICAL]
    assert pane.model.rowCount() == 0
    apply_style = Mock(wraps=runtime.application.setStyleSheet)
    monkeypatch.setattr(runtime.application, "setStyleSheet", apply_style)
    update_settings = Mock(wraps=runtime.controller.update_settings)
    monkeypatch.setattr(runtime.controller, "update_settings", update_settings)

    for _ in range(3):
        QTest.mouseClick(pane.hide_completed, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
        runtime.application.processEvents()
        assert pane.model.rowCount() == 1
        assert not runtime.window.workspace.tasks.hide_completed.isChecked()
        assert not runtime.window.patient_panel.sidebar_tasks.hide_completed.isChecked()
        QTest.mouseClick(pane.hide_completed, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
        runtime.application.processEvents()
        assert pane.model.rowCount() == 0
    assert update_settings.call_count == 6
    assert apply_style.call_count == 0
    runtime.window._set_completed_visibility(True)
    assert update_settings.call_count == 7
    assert all(not item.hide_completed.isChecked() for item in board.panes.values())
    assert all(
        value is False
        for value in runtime.controller.settings().user_preferences["task_hide_completed"].values()
    )
    assert runtime.window._patient_popup is None
    assert runtime.window._error_dialog is None
    board.close()
    runtime.application.processEvents()
    assert not board.isVisible()


def test_error_storm_uses_one_nonblocking_dismissible_window(runtime, monkeypatch):
    def blocking_warning(*args, **kwargs):
        pytest.fail("An asynchronous failure must not enter QMessageBox.warning's nested loop")

    monkeypatch.setattr(QMessageBox, "warning", blocking_warning)
    for index in range(40):
        runtime.controller.error_raised.emit("Failed operation", f"Failure {index}")
        runtime.recovery.failure.emit("Recovery unavailable")
        runtime.application.processEvents()
    dialog = runtime.window._error_dialog
    assert dialog is not None and dialog.isVisible()
    assert QApplication.activeModalWidget() is None
    assert (
        len(
            [
                widget
                for widget in QApplication.topLevelWidgets()
                if isinstance(widget, QMessageBox) and widget.isVisible()
            ]
        )
        == 1
    )
    assert "Failure 39" in dialog.detailedText()
    QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    runtime.application.processEvents()
    assert runtime.window._error_dialog is None
    runtime.application.processEvents()
    assert runtime.window._error_dialog is None
    runtime.controller.error_raised.emit("New operation", "A later, separate error")
    assert runtime.window._error_dialog is not None
    runtime.window._error_dialog.close()
    assert runtime.window._error_dialog is None


def test_hide_completed_with_settings_failure_does_not_stack_windows(runtime, monkeypatch):
    board = _board(runtime)
    runtime.window.hide()
    monkeypatch.setattr(
        runtime.controller.services.settings,
        "update",
        Mock(side_effect=SettingsValidationError("Preference file unavailable")),
    )
    pane = board.panes[TaskCategory.CLINICAL]
    for _ in range(6):
        pane.hide_completed.click()
        runtime.application.processEvents()
    dialog = runtime.window._error_dialog
    assert dialog is not None and dialog.isVisible()
    assert not dialog.isModal()
    assert dialog.parentWidget() is board
    dialog.close()
    board.close()
    runtime.application.processEvents()
    assert runtime.window._error_dialog is None
    assert not board.isVisible()


def test_recovery_retries_without_reopening_same_failure(runtime):
    service = Mock()
    service.poll.side_effect = RecoveryServiceError("Recovery storage unavailable")
    adapter = QtRecoveryAdapter(service)
    failures = []

    def failed(message):
        failures.append(message)
        # A callback may pump events or invoke the scheduler again.
        adapter._poll()

    adapter.failure.connect(failed)
    for _ in range(20):
        adapter._poll()
    assert service.poll.call_count == 20
    assert failures == ["Recovery storage unavailable"]
    service.poll.side_effect = None
    service.poll.return_value = True
    adapter._poll()
    service.poll.side_effect = RecoveryServiceError("Recovery storage unavailable")
    adapter._poll()
    assert len(failures) == 2


def test_resize_does_not_open_patient_popup_over_modal_dialog(runtime):
    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic resize patient", species="Canine"
    )
    modal = QDialog(runtime.window)
    modal.setModal(True)
    modal.show()
    try:
        runtime.window.resize(780, 550)
        runtime.application.processEvents()
        assert runtime.window._patient_popup is None
        assert runtime.window.isVisible()
    finally:
        modal.close()


def test_real_theme_change_still_applies(runtime):
    before = runtime.application.styleSheet()
    selected = runtime.controller.settings().theme
    alternative = "light" if selected != "light" else "dark"
    assert runtime.controller.update_settings(theme=alternative) is not None
    assert runtime.application.styleSheet() != before


def test_temporary_resize_or_minimize_cancels_queued_patient_popup(runtime):
    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic transient resize patient", species="Canine"
    )
    runtime.window.resize(780, 550)
    runtime.window.resize(1000, 700)
    runtime.application.processEvents()
    assert runtime.window._patient_popup is None
    runtime.window.resize(780, 550)
    runtime.window.showMinimized()
    runtime.application.processEvents()
    assert runtime.window._patient_popup is None
    runtime.window.showNormal()


def test_failed_close_reports_once_and_keeps_app_available(runtime, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(runtime.controller, "shutdown", lambda: False)
        assert runtime.window.close() is False
        assert runtime.window.isVisible()
        dialog = runtime.window._error_dialog
        assert dialog is not None
        assert runtime.window.close() is False
        assert runtime.window._error_dialog is dialog
        dialog.close()
        assert runtime.window.isVisible()
