"""Main shell and controlled-shutdown tests."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGroupBox, QLabel, QMessageBox, QPushButton

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def make_runtime(tmp_path: Path):
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
        )
    )
    return create_runtime(["icu-patient-tracker"], config_path)


def test_main_window_shell_actions_theme_and_empty_state(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        runtime.window.show()
        runtime.application.processEvents()
        actions = runtime.window.actions_by_name
        assert runtime.window.patient_panel.model.rowCount() == 0
        assert actions["new_patient"].shortcut() == QKeySequence("Ctrl+N")
        assert actions["save"].shortcut() == QKeySequence("Ctrl+S")
        assert runtime.application.styleSheet()
        assert runtime.autosave.is_active

        QTest.keyClick(runtime.window, Qt.Key.Key_Escape)
        runtime.application.processEvents()
        assert runtime.window.isVisible()
    finally:
        runtime.shutdown()


def test_main_window_uses_legacy_reference_workspace_composition(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        window = runtime.window
        group_titles = {group.title() for group in window.findChildren(QGroupBox)}

        assert {"Actions", "Filters", "Status", "Patient Summary", "Day Workspace"} <= (
            group_titles
        )
        assert {
            "Pertinent exam findings (AM)",
            "Diagnostics",
            "Treatment changes (AM)",
            "Devices",
            "Assessment (AM)",
        } <= group_titles
        assert not window.workspace.charting.diagnostics.isHidden()
        assert "Additional summary" not in {
            label.text() for label in window.workspace.charting.findChildren(QLabel)
        }
        assert (
            window.workspace.charting.diagnostic_result_editor
            is window.workspace.charting.diagnostics
        )
        assert not window.workspace.charting.assessment.isHidden()
        assert window.patient_panel.patients_mode_button.text() == "[Patients]"
        assert window.patient_panel.tasks_mode_button.text() == "Tasks"
        window.patient_panel.show_tasks_mode()
        assert window.patient_panel.sidebar_stack.currentWidget() is window.patient_panel.task_page
        assert window.patient_panel.tasks_mode_button.text() == "[Tasks]"
        window.patient_panel.show_patients_mode()
        assert window.patient_panel.status_filter.isHidden()
        assert window.workspace.tabs.indexOf(window.workspace.patient_summary) == -1
        assert window.workspace.tabs.tabText(0) == "[Charting]"
        soap_index = window.workspace.tabs.indexOf(window.workspace.soap)
        assert window.workspace.tabs.tabText(soap_index) == "[SOAP]"
        assert window.workspace.previous_button.text() == "<"
        assert window.workspace.next_button.text() == ">"
        assert window.workspace.patient_summary.task_board_button.text() == "Task Board"
        assert window.workspace.patient_summary.save_now_button.text() == "Save Now"
        button_texts = {
            button.text() for button in window.workspace.findChildren(QPushButton)
        }
        assert "Refresh SOAP from AM Charting" not in button_texts
        assert "Refresh selected mapping" not in button_texts
        assert "Save and sync recognized fields" not in button_texts
        assert window.workspace.tabs.indexOf(window.workspace.instrumentation) == -1
        assert window.workspace.charting.instrumentation is window.workspace.instrumentation
        assert window._toolbar.isHidden()
        assert window.menuBar().isHidden()
    finally:
        runtime.shutdown()


def test_patient_header_save_indicator_tracks_persistence_state(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        indicator = runtime.window.workspace.save_indicator
        assert indicator.toolTip() == "No patient selected"

        patient = runtime.controller.services.patients.create(name="Bella", species="Canine")
        assert runtime.controller.select_patient(patient.id)
        assert indicator.toolTip() == "Saved"
        assert "#2da44e" in indicator.styleSheet()

        runtime.controller.mark_editor_dirty("test-editor", lambda: None)
        assert indicator.toolTip() == "Save scheduled"
        assert "#bf8700" in indicator.styleSheet()

        runtime.controller.save_status_changed.emit("Save failed")
        assert indicator.toolTip() == "Save failed — changes remain unsaved"
        assert "#cf222e" in indicator.styleSheet()
        assert indicator.accessibleName() == "Save status: Save failed — changes remain unsaved"
    finally:
        runtime.controller.flush_pending()
        runtime.shutdown()


def test_sidebar_can_be_collapsed_and_reopened_from_persistent_toggle(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        window = runtime.window
        window.show()
        runtime.application.processEvents()
        window.patient_panel.show_tasks_mode()
        original_width = window._splitter.sizes()[0]
        assert window.sidebar_toggle_button.width() <= 16
        assert window.sidebar_toggle_button.height() <= 16
        assert window.sidebar_toggle_button.parentWidget() is window.sidebar_toggle_rail
        assert window.sidebar_toggle_rail.isVisible()

        window.sidebar_toggle_button.click()
        runtime.application.processEvents()

        assert window.patient_panel.isHidden()
        assert window.sidebar_toggle_button.isVisible()
        assert window.sidebar_toggle_rail.isVisible()
        assert window.sidebar_toggle_button.text() == ">"

        window.sidebar_toggle_button.click()
        runtime.application.processEvents()

        assert window.patient_panel.isVisible()
        assert window.patient_panel.sidebar_stack.currentWidget() is window.patient_panel.task_page
        assert window.sidebar_toggle_button.text() == "<"
        assert abs(window._splitter.sizes()[0] - original_width) <= 20
    finally:
        runtime.shutdown()


def test_running_problem_projection_and_patient_search_window(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        first = runtime.controller.services.patients.create(name="Bella", species="Canine")
        runtime.controller.services.patients.create(name="Milo", species="Feline")
        assert runtime.controller.select_patient(first.id)
        assert runtime.controller.add_problem("Aspiration pneumonia") is not None
        assert "Aspiration pneumonia" in (
            runtime.window.workspace.patient_summary.running_problems.toPlainText()
        )
        summary = runtime.window.workspace.patient_summary
        assert [summary.species.itemText(index) for index in range(2)] == ["Canine", "Feline"]
        summary.running_problems.setPlainText("Aspiration pneumonia\nHypoglycemia")
        assert summary.apply_problem_list()
        assert [problem.title for problem in runtime.controller.problems()] == [
            "Aspiration pneumonia",
            "Hypoglycemia",
        ]

        runtime.window._show_patient_search()
        dialog = runtime.window._patient_search_dialog
        assert dialog is not None
        dialog.search.setText("Milo")
        assert dialog.model.rowCount() == 1
        dialog._activate()
        assert runtime.controller.selected_patient() is not None
        assert runtime.controller.selected_patient().name == "Milo"
    finally:
        runtime.shutdown()


def test_failed_shutdown_keeps_window_open(tmp_path: Path, monkeypatch) -> None:
    runtime = make_runtime(tmp_path)
    runtime.window.show()
    monkeypatch.setattr(runtime.controller, "shutdown", lambda: False)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: QMessageBox.StandardButton.Ok)
    assert runtime.window.close() is False
    assert runtime.window.isVisible()
    monkeypatch.setattr(runtime.controller, "shutdown", lambda: True)
    runtime.shutdown()


def test_geometry_is_restored_through_settings_service(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    runtime.window.resize(780, 550)
    assert runtime.shutdown()

    relaunched = create_runtime(["icu-patient-tracker"], tmp_path / "config.json")
    try:
        assert relaunched.window.size().width() == 780
        assert relaunched.window.size().height() == 550
    finally:
        relaunched.shutdown()
