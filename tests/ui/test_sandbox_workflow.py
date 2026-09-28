"""Headless Slice 9 Sandbox editor tests."""

from pathlib import Path

from PySide6.QtGui import QTextCursor

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def test_sandbox_tab_saves_exact_text_without_implicit_extraction(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        assert runtime.window.patient_panel.create_patient(mrn=None, name="Bella", species="Canine")
        panel = runtime.window.workspace.sandbox
        text = "## Ideas\n- [ ] CBC | urgent\n#INPUT#\n"
        panel.editor.setPlainText(text)

        assert panel.save()
        assert runtime.controller.preview_sandbox_tasks() is not None
        assert runtime.controller.tasks() == ()
        assert panel.editor.toPlainText() == text

        cursor = panel.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        panel.editor.setTextCursor(cursor)
        assert panel._move_input(False)
        assert panel.editor.textCursor().selectedText() == "#INPUT#"
    finally:
        runtime.shutdown()
