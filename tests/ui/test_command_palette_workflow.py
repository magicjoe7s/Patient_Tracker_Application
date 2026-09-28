"""Registry-driven commands, generated help, and keyboard workflow tests."""

from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.enums import AdmissionStatus, TaskCategory


def _runtime(tmp_path: Path) -> ApplicationRuntime:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=0,
        )
    )
    return create_runtime(["icu-patient-tracker"], config_path)


def test_actions_menus_and_help_are_generated_from_one_registry(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        window = runtime.window
        actions = window.actions_by_name

        assert set(actions) == {definition.name for definition in window._registry.definitions}
        for definition in window._registry.definitions:
            expected = [QKeySequence(value) for value in definition.shortcuts]
            assert actions[definition.name].shortcuts() == expected

        window._show_generated_help()
        assert window._help_dialog is not None
        assert window._help_dialog.text.toPlainText() == window._registry.help_text()
        menu_titles = [action.text().replace("&", "") for action in window.menuBar().actions()]
        assert menu_titles == ["File", "Navigate", "View", "Tools", "Help"]
    finally:
        runtime.shutdown()


def test_typed_commands_select_navigate_readmit_and_focus(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        patients = runtime.controller.services.patients
        first = patients.create(name="Bella", species="Canine")
        second = patients.create(name="Milo", species="Feline")
        second_day = runtime.controller.services.days.create(
            second.id,
            start_at=second.hospital_days[0].start_at + timedelta(days=1),
            label="postop",
        )
        assert runtime.controller.select_patient(first.id)

        assert runtime.window.execute_command("p milo")
        assert runtime.controller.context.patient_id == second.id
        assert runtime.window.execute_command("day postop")
        assert runtime.controller.context.hospital_day_id == second_day.id
        assert runtime.window.execute_command("prev")
        assert runtime.controller.context.patient_id == first.id
        assert runtime.window.execute_command("status home")
        assert patients.get(first.id).admission_status is AdmissionStatus.DISCHARGED
        assert runtime.window.execute_command("readmit bella")
        assert patients.get(first.id).admission_status is AdmissionStatus.ADMITTED

        runtime.window.show()
        assert runtime.window.execute_command("focus pending")
        runtime.application.processEvents()
        assert runtime.window.workspace.tabs.currentWidget() is runtime.window.workspace.tasks
        assert runtime.window.workspace.tasks.selected_category() is TaskCategory.DIAGNOSTIC
        assert runtime.window.workspace.tasks.list_view.hasFocus()

        assert runtime.window.execute_command("hide done")
        assert runtime.window.workspace.tasks.hide_completed.isChecked()
        assert runtime.window.execute_command("show completed")
        assert not runtime.window.workspace.tasks.hide_completed.isChecked()
    finally:
        runtime.shutdown()


def test_primary_shortcuts_dispatch_without_overriding_native_editor_keys(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        first = runtime.controller.services.patients.create(name="First", species="Canine")
        second = runtime.controller.services.patients.create(name="Second", species="Feline")
        assert runtime.controller.select_patient(first.id)
        window = runtime.window
        window.show()
        window.activateWindow()
        runtime.application.processEvents()
        window.setFocus()
        invoked: list[str] = []
        window._action_handlers["command_palette"] = lambda _argument: invoked.append("palette")
        window._action_handlers["new_todo"] = lambda _argument: invoked.append("todo")

        QTest.keyClick(window.centralWidget(), Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(window.centralWidget(), Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(
            window.centralWidget(),
            Qt.Key.Key_L,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        runtime.application.processEvents()

        assert invoked == ["palette", "todo"]
        assert runtime.controller.context.patient_id == second.id

        editor = window.workspace.charting.summary
        editor.setPlainText("native editing")
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert editor.textCursor().selectedText() == "native editing"
    finally:
        runtime.shutdown()
