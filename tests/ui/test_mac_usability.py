"""Mac-only entry and chart views with unchanged Windows presentation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.ui import main_window, models
from icu_patient_tracker.widgets import day_workspace, instrumentation_panel, patient_panel


def make_runtime(tmp_path: Path, monkeypatch, platform: str = "darwin"):
    for module in (day_workspace, instrumentation_panel, patient_panel, main_window, models):
        monkeypatch.setattr(module, "sys", SimpleNamespace(platform=platform))
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(AppConfig(
        database_path=tmp_path / "tracker.sqlite3",
        backup_directory=tmp_path / "backups",
        autosave_debounce_seconds=0.5,
    ))
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    runtime.controller.error_raised.disconnect()
    assert runtime.window.patient_panel.create_patient(
        mrn=None, name="Synthetic patient with a very long name", species="Canine"
    )
    return runtime


@pytest.mark.parametrize("label", [choice[0] for choice in instrumentation_panel._DEVICE_CHOICES])
def test_mac_device_prompts_accept_blank_details(tmp_path, monkeypatch, label):
    runtime = make_runtime(tmp_path, monkeypatch)
    prompts = []

    def answer(*args, **kwargs):
        prompts.append((args[2], kwargs.get("text", "")))
        return "", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    try:
        panel = runtime.window.workspace.instrumentation
        panel.checkboxes[label].setChecked(True)
        devices = runtime.controller.devices()
        assert len(devices) == 1
        device = devices[0]
        assert device.placed_at is None
        assert device.size is None
        assert prompts[-1][1] == ""
        panel.refresh(force=True)
        assert panel.checkboxes[label].isChecked()
        assert "placed" not in panel.editor.toPlainText()
        assert "None" not in panel.editor.toPlainText()
        runtime.controller.create_day(datetime.now(UTC) + timedelta(days=1))
        assert runtime.controller.devices()[0].placed_at is None
        carried = runtime.controller.devices()[0]
        panel.checkboxes[label].setChecked(False)
        assert runtime.controller.devices()[0].id == carried.id
        assert runtime.controller.devices()[0].removed_at is not None
    finally:
        runtime.shutdown()


@pytest.mark.parametrize("cancel_at", [0, 1, 2])
def test_device_cancel_never_creates_partial_record(tmp_path, monkeypatch, cancel_at):
    runtime = make_runtime(tmp_path, monkeypatch)
    answers = iter([("20ga", True), ("cephalic", True), ("2026-10-19", True)])
    position = 0

    def answer(*args, **kwargs):
        nonlocal position
        result = next(answers)
        accepted = position != cancel_at
        position += 1
        return result[0], accepted

    monkeypatch.setattr(QInputDialog, "getText", answer)
    try:
        panel = runtime.window.workspace.instrumentation
        panel.checkboxes["Peripheral IVC"].setChecked(True)
        assert runtime.controller.devices() == ()
        assert not panel.checkboxes["Peripheral IVC"].isChecked()
    finally:
        runtime.shutdown()


def test_mac_invalid_date_is_rejected_but_partial_details_save(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path, monkeypatch)
    answers = iter([("", True), ("cephalic", True), ("bad-date", True),
                    ("20ga", True), ("", True), ("2026-10-19", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: next(answers))
    # Avoid opening a modal validation error during the test.
    try:
        panel = runtime.window.workspace.instrumentation
        panel.checkboxes["Peripheral IVC"].setChecked(True)
        assert runtime.controller.devices() == ()
        panel.checkboxes["Peripheral IVC"].setChecked(True)
        device = runtime.controller.devices()[0]
        assert device.size == "20ga"
        assert device.anatomical_location == ""
        assert device.placed_at.date().isoformat() == "2026-10-19"
    finally:
        runtime.shutdown()


def test_compact_dx_shares_document_save_recovery_and_context(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path, monkeypatch)
    try:
        chart = runtime.window.workspace.charting
        mini = chart.mini_diagnostics
        assert mini is not None
        assert chart.chart_detail_tabs.currentIndex() == 0
        assert mini.document() is chart.diagnostics.document()
        mini.setPlainText("CBC: mild anemia")
        assert chart.diagnostics.toPlainText() == "CBC: mild anemia"
        assert chart.recovery_values()["clinical_summary"] == "CBC: mild anemia"
        assert runtime.controller.context.is_dirty
        assert runtime.controller.flush_pending()
        assert "mild anemia" in runtime.controller.diagnostic_text(
            runtime.controller.context.patient_id, runtime.controller.context.hospital_day_id
        )
        first_id = runtime.controller.context.patient_id
        runtime.window.show()
        mini.setFocus()
        QApplication.processEvents()
        mini.setPlainText("CBC: unsaved edit")
        chart.refresh_diagnostic_results()
        assert mini.toPlainText() == "CBC: unsaved edit"
        assert chart.save()
        runtime.window.patient_panel.create_patient(
            mrn=None, name="Second synthetic patient", species="Feline"
        )
        assert mini.toPlainText() == ""
        runtime.controller.select_patient(first_id)
        assert "unsaved edit" in mini.toPlainText()
        chart.diagnostics.setPlainText("Chemistry: normal")
        assert mini.toPlainText() == "Chemistry: normal"
        values = chart.recovery_values()
        mini.clear()
        chart.apply_recovery(values)
        assert "normal" in mini.toPlainText()
    finally:
        runtime.shutdown()


def test_mac_sidebar_can_shrink_and_remembers_width(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path, monkeypatch)
    try:
        window = runtime.window
        window.show()
        QApplication.processEvents()
        window._splitter.setSizes([150, 18, 1100])
        QApplication.processEvents()
        assert window.patient_panel.width() <= 155
        width = window.patient_panel.width()
        window._toggle_sidebar()
        window._toggle_sidebar()
        QApplication.processEvents()
        assert abs(window.patient_panel.width() - width) <= 5
        # Explicit Qt elision retains full underlying patient text.
        assert window.patient_panel.list_view.textElideMode() == Qt.TextElideMode.ElideRight
        tooltip = window.patient_panel.model.data(
            window.patient_panel.model.index(0, 0), Qt.ItemDataRole.ToolTipRole
        )
        assert "Synthetic patient with a very long name" in tooltip
        window.grab().save(str(tmp_path / "mac-sidebar-preview.png"))
    finally:
        runtime.shutdown()
    config = ConfigManager(tmp_path / "config.json").load()
    assert config.user_preferences["splitter_sizes"][0] <= 155


def test_windows_keeps_existing_chart_and_device_requirements(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path, monkeypatch, "win32")
    answers = iter([("", True), ("", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: next(answers))
    try:
        assert runtime.window.workspace.charting.mini_diagnostics is None
        panel = runtime.window.workspace.instrumentation
        panel.checkboxes["Peripheral IVC"].setChecked(True)
        assert runtime.controller.devices() == ()
    finally:
        runtime.shutdown()
