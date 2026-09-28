"""Headless Slice 10 clipboard and visible EMR-state tests."""

from datetime import date
from pathlib import Path

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def test_copy_actions_use_system_clipboard_and_show_day_upload_state(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            minimize_after_copy=False,
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn="123456", name="Bella", species="Canine"
        )
        charting = runtime.window.workspace.charting
        charting.treatment.setPlainText("Continue fluids")
        charting.examination.setPlainText("Bright")
        charting.assessment.setPlainText("Stable")
        assert runtime.controller.copy_chart()
        chart_text = runtime.application.clipboard().text().replace("\r\n", "\n")
        assert chart_text.startswith(f"Bella | {date.today():%b %d, '%y}")
        assert "Treatment changes:\nContinue fluids" in chart_text
        assert runtime.window.workspace.emr_uploaded.isChecked() is False

        soap = runtime.window.workspace.soap
        assert soap.save()
        assert soap.copy_to_clipboard()
        assert (
            runtime.application.clipboard().text().startswith("# Day #INPUT# ICU hospitalization")
        )
        selected_day = runtime.controller.selected_day()
        assert selected_day is not None
        assert selected_day.emr_uploaded is True
        assert runtime.window.workspace.emr_uploaded.isChecked()
        assert runtime.window.workspace.emr_badge.text() == "SOAP IN EMR"

        summary = runtime.window.workspace.patient_summary
        summary.copy_name_button.click()
        assert runtime.application.clipboard().text() == "Bella"
        runtime.window.showNormal()
        summary.copy_mrn_button.click()
        assert runtime.application.clipboard().text() == "123456"
        assert runtime.window.isMinimized()
    finally:
        runtime.shutdown()
