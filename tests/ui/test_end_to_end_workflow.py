"""Restart-safe widget-to-SQLite presentation workflow."""

import re
from pathlib import Path

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def test_complete_ui_workflow_survives_restart(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=0,
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        window = runtime.window
        window.show()
        runtime.application.processEvents()
        assert window.patient_panel.create_patient(mrn="A100", name="Bella", species="Canine")
        day = runtime.controller.selected_day()
        assert day is not None
        assert window.workspace.problems.add_problem("Anemia")
        assert window.workspace.tasks.add_task("Recheck PCV")
        window.workspace.instrumentation.editor.setPlainText("PIV — left cephalic")
        assert window.workspace.instrumentation.save()
        charting = window.workspace.charting
        charting.diagnostics.setPlainText("Comfortable after surgery")
        charting.assessment.setPlainText("Stable perfusion")
        soap = window.workspace.soap
        assert soap.save()
        soap.markdown.setPlainText(
            re.sub(
                r"(?m)^\*\*One Liner:\*\*.*$",
                "**One Liner:** Rested overnight",
                soap.markdown.toPlainText(),
            )
        )
        assert soap.save()
        window.patient_panel.search.setText("Bella")
        runtime.application.processEvents()
        assert window.patient_panel.model.rowCount() == 1
    finally:
        assert runtime.shutdown()

    relaunched = create_runtime(["icu-patient-tracker"], config_path)
    try:
        window = relaunched.window
        window.show()
        window.patient_panel.search.setText("Bella")
        relaunched.application.processEvents()
        assert window.patient_panel.model.rowCount() == 1
        index = window.patient_panel.model.index(0, 0)
        window.patient_panel.list_view.clicked.emit(index)
        relaunched.application.processEvents()
        selected = relaunched.controller.selected_patient()
        assert selected is not None
        assert selected.mrn == "A100"
        assert window.workspace.day_combo.count() == 1
        assert window.workspace.problems.model.rowCount() == 1
        task_model = window.workspace.tasks.model
        task_rows = [
            task_model.data(task_model.index(row, 0))
            for row in range(task_model.rowCount())
        ]
        assert task_model.rowCount() == 2, task_rows
        assert window.workspace.instrumentation.editor.toPlainText() == "PIV — left cephalic"
        assert "**One Liner:** Rested overnight" in window.workspace.soap.markdown.toPlainText()
        assert (
            window.workspace.charting.diagnostics.toPlainText()
            == "- [ ] Comfortable after surgery"
        )
    finally:
        assert relaunched.shutdown()
