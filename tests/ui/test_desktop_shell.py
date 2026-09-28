"""Resident shell, global-hotkey, tray, and single-instance tests."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.app.single_instance import SingleInstanceCoordinator
from icu_patient_tracker.domain.enums import TaskCategory, TaskStatus
from icu_patient_tracker.resources.application_icon import load_application_icon
from icu_patient_tracker.ui.global_hotkeys import GlobalHotkeyManager
from icu_patient_tracker.ui.tray_adapter import DesktopTrayAdapter


class FakeHotkeyBackend:
    def __init__(self) -> None:
        self.registered: list[tuple[int, int, int]] = []
        self.unregistered: list[int] = []

    def register(self, identifier: int, modifiers: int, virtual_key: int) -> bool:
        self.registered.append((identifier, modifiers, virtual_key))
        return True

    def unregister(self, identifier: int) -> None:
        self.unregistered.append(identifier)


def make_runtime(tmp_path: Path):
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
        )
    )
    return create_runtime(["icu-patient-tracker"], config_path)


def test_application_icon_is_available_to_qt_shell(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        icon = load_application_icon()
        assert not icon.isNull()
        assert not runtime.application.windowIcon().isNull()
        assert not runtime.window.windowIcon().isNull()
    finally:
        runtime.shutdown()


def test_single_instance_claims_and_releases_process_resources(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    primary = SingleInstanceCoordinator(tmp_path / "instance")
    replacement = SingleInstanceCoordinator(tmp_path / "instance")
    try:
        (tmp_path / "instance").mkdir()
        assert primary.acquire_or_notify()
        assert primary.owns_instance
        primary.close()
        assert replacement.acquire_or_notify()
        assert replacement.owns_instance
    finally:
        replacement.close()
        primary.close()
        runtime.shutdown()


def test_global_hotkeys_register_dispatch_and_release(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    backend = FakeHotkeyBackend()
    calls: list[str] = []
    manager = GlobalHotkeyManager(
        {
            "toggle_application": lambda: calls.append("application"),
            "toggle_task_board": lambda: calls.append("board"),
            "capture_diagnostic_result": lambda: calls.append("result"),
        },
        backend=backend,
        application=runtime.application,
    )
    try:
        manager.start()

        assert manager.registered_labels == (
            "Shift+Alt+I",
            "Alt+Shift+T",
            "Alt+Shift+R",
        )
        for identifier, _modifiers, _virtual_key in backend.registered:
            assert manager.dispatch(identifier)
        assert calls == ["application", "board", "result"]
        assert not manager.dispatch(999)

        manager.stop()
        assert sorted(backend.unregistered) == sorted(row[0] for row in backend.registered)
    finally:
        manager.stop()
        runtime.shutdown()


def test_diagnostic_capture_saves_results_and_completes_matching_task(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        patient = runtime.controller.create_patient(name="Bella", species="Canine")
        assert patient is not None
        assert runtime.controller.select_patient(patient.id)
        task = runtime.controller.add_task("CBC", category=TaskCategory.DIAGNOSTIC)
        assert task is not None

        runtime.window.show_diagnostic_result_capture()
        dialog = runtime.window._diagnostic_result_dialog
        assert dialog is not None
        runtime.application.processEvents()
        assert runtime.window.isMinimized()
        assert dialog.isVisible()
        dialog.result_edit.setPlainText("Preliminary result")
        dialog.save_button.click()
        stored = runtime.controller.diagnostic_tasks_for(task.patient_id, task.hospital_day_id)[0]
        assert stored.status is TaskStatus.COMPLETED
        assert stored.diagnostic_result is not None
        assert stored.diagnostic_result.result_text == "Preliminary result"

        dialog.result_edit.setPlainText("Mild anemia; platelets adequate")
        dialog.save_button.click()
        stored = runtime.controller.diagnostic_tasks_for(task.patient_id, task.hospital_day_id)[0]
        assert stored.status is TaskStatus.COMPLETED
        assert runtime.controller.diagnostic_result_line(stored) == (
            "- [x] CBC: Mild anemia; platelets adequate"
        )
    finally:
        runtime.shutdown()


def test_escape_and_close_hide_resident_window_and_board_stays_on_top(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        window = runtime.window
        window.enable_tray_residency()
        window.show()
        runtime.application.processEvents()

        QTest.keyClick(window, Qt.Key.Key_Escape)
        runtime.application.processEvents()
        assert not window.isVisible()

        window.activate_main_window()
        assert window.close() is False
        assert not window.isVisible()

        window.toggle_task_board()
        board = window._task_board_dialog
        assert board is not None
        assert board.isVisible()
        assert board.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        window.toggle_task_board()
        assert not board.isVisible()
    finally:
        runtime.shutdown()


def test_tray_actions_use_injected_shell_operations(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    tray_icon = QSystemTrayIcon()
    visible = [False]
    pinned = [False]
    calls: list[str] = []

    def toggle_window() -> None:
        visible[0] = not visible[0]
        calls.append("toggle")

    def set_pinned(value: bool) -> None:
        pinned[0] = value
        calls.append(f"pin:{value}")

    adapter = DesktopTrayAdapter(
        tray_icon,
        is_window_visible=lambda: visible[0],
        is_window_pinned=lambda: pinned[0],
        toggle_window=toggle_window,
        show_task_board=lambda: calls.append("board"),
        set_window_pinned=set_pinned,
        exit_application=lambda: calls.append("exit"),
    )

    adapter.show_hide_action.trigger()
    adapter.task_board_action.trigger()
    adapter.pin_action.setChecked(True)
    adapter.exit_action.trigger()
    adapter.refresh()

    assert calls == ["toggle", "board", "pin:True", "exit"]
    assert adapter.show_hide_action.text() == "Hide ICU Patient Tracker"
    assert adapter.pin_action.isChecked()
    adapter.close()
    runtime.shutdown()
