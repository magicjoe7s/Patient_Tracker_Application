"""Headless Slice 15 analytics dialog integration tests."""

from pathlib import Path

from PySide6.QtGui import QKeySequence

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


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


def test_analytics_action_opens_read_only_report_and_copies_snapshot(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        action = runtime.window.actions_by_name["analytics"]
        assert action.shortcuts() == [QKeySequence("Ctrl+Alt+A")]
        assert runtime.window.execute_command("report")
        dialog = runtime.window._analytics_dialog

        assert dialog is not None and dialog.isVisible()
        assert dialog.report.isReadOnly()
        assert "- Total patients: 0" in dialog.report.toPlainText()
        assert dialog.copy_report()
        copied = runtime.application.clipboard().text().replace("\r\n", "\n")
        assert copied == dialog.report.toPlainText()
    finally:
        runtime.shutdown()


def test_visible_analytics_refreshes_after_domain_change(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.window._show_analytics()
        dialog = runtime.window._analytics_dialog
        assert dialog is not None
        assert dialog.snapshot is not None and dialog.snapshot.total_patients == 0

        runtime.controller.services.patients.create(name="Bella", species="Canine")
        runtime.application.processEvents()

        assert dialog.snapshot is not None and dialog.snapshot.total_patients == 1
        assert "- Active census: 1" in dialog.report.toPlainText()
    finally:
        runtime.shutdown()
