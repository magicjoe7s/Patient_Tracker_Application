"""Headless canonical SOAP editor workflow tests."""

from pathlib import Path

from PySide6.QtGui import QTextCursor

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.enums import Acuity, CodeStatus


def test_canonical_editor_uses_configured_staff_and_wraps_input_navigation(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            soap_daytime_resident="Dr. Configured",
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        assert runtime.window.patient_panel.create_patient(mrn=None, name="Bella", species="Canine")
        panel = runtime.window.workspace.soap
        assert panel.markdown.toPlainText().startswith("# Day #INPUT# ICU hospitalization")
        assert "**Code Status:** CPR" in panel.markdown.toPlainText()
        assert "**Clinical Trend:** #INPUT#" in panel.markdown.toPlainText()
        assert "## **Recommendations**" in panel.markdown.toPlainText()
        assert panel.save()
        assert "*Daytime primary ICU resident:* Dr. Configured" in panel.markdown.toPlainText()

        cursor = panel.markdown.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        panel.markdown.setTextCursor(cursor)
        assert panel.focus_next_placeholder()
        assert panel.markdown.textCursor().selectedText() == "#INPUT#"
        first_position = panel.markdown.textCursor().selectionStart()
        assert panel.focus_previous_placeholder()
        assert panel.markdown.textCursor().selectedText() == "#INPUT#"
        assert panel.markdown.textCursor().selectionStart() > first_position
    finally:
        runtime.shutdown()


def test_code_status_and_daily_acuity_synchronize_with_soap_both_directions(
    tmp_path: Path,
) -> None:
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
        summary = runtime.window.workspace.patient_summary
        charting = runtime.window.workspace.charting
        soap = runtime.window.workspace.soap
        assert [summary.code_status.itemText(index) for index in range(4)] == [
            "CPR",
            "DNR",
            "DVM discretion",
            "DNR with assist",
        ]
        assert [charting.acuity.itemText(index) for index in range(5)] == [
            "#INPUT#",
            "Stable",
            "Watcher",
            "Unstable",
            "Critical",
        ]

        summary.code_status.setCurrentIndex(summary.code_status.findData(CodeStatus.DNR_ASSIST))
        charting.acuity.setCurrentIndex(charting.acuity.findData(Acuity.UNSTABLE))
        assert runtime.controller.flush_pending()
        runtime.application.processEvents()

        markdown = runtime.controller.selected_day().soap_documents[-1].markdown_text
        assert "**Code Status:** DNR with assist" in markdown
        assert "**Clinical Trend:** unstable" in markdown

        edited = markdown.replace(
            "**Code Status:** DNR with assist", "**Code Status:** DVM discretion"
        ).replace("**Clinical Trend:** unstable", "**Clinical Trend:** critical")
        soap.markdown.setPlainText(edited)
        assert soap.save()
        assert runtime.controller.flush_pending()
        runtime.application.processEvents()

        patient = runtime.controller.selected_patient()
        day = runtime.controller.selected_day()
        assert patient is not None and day is not None
        assert patient.code_status is CodeStatus.DVM_DISCRETION
        assert day.acuity is Acuity.CRITICAL
        assert summary.code_status.currentData() == CodeStatus.DVM_DISCRETION
        assert summary.acuity.currentData() == Acuity.CRITICAL
        assert charting.acuity.currentData() == Acuity.CRITICAL
    finally:
        runtime.shutdown()


def test_am_charting_refresh_preserves_pm_and_recommendation_content(tmp_path: Path) -> None:
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
        soap = runtime.window.workspace.soap
        existing = (
            soap.markdown.toPlainText()
            .replace("**PM:**\n- #INPUT#", "**PM:**\n- Overnight exam", 1)
            .replace("**PM**\n- #INPUT#", "**PM**\n- Overnight assessment", 1)
            .replace(
                "*Diagnostics*\n- #INPUT#",
                "*Diagnostics*\n- Recheck CBC overnight",
                1,
            )
        )
        soap.markdown.setPlainText(existing)
        assert soap.save()

        charting = runtime.window.workspace.charting
        charting.examination.setPlainText("BAR; hydrated")
        charting.diagnostics.setPlainText("CBC stable\nChemistry normal")
        charting.treatment.setPlainText("Reduce crystalloid rate")
        charting.assessment.setPlainText("Perfusion improving")
        assert charting.save()

        refreshed = soap.markdown.toPlainText()
        assert "**AM:**\n- BAR; hydrated" in refreshed
        assert "**Diagnostic Summary**\n- [ ] CBC stable\n- [ ] Chemistry normal" in refreshed
        assert "**Treatment changes**\n- Reduce crystalloid rate" in refreshed
        assert "**AM**\n- Perfusion improving" in refreshed
        assert "**PM:**\n- Overnight exam" in refreshed
        assert "**PM**\n- Overnight assessment" in refreshed
        assert "*Diagnostics*\n- Recheck CBC overnight" in refreshed

        day = runtime.controller.selected_day()
        assert day is not None
        assert day.clinical_summary == ""
        assert [task.title for task in runtime.controller.tasks()] == [
            "CBC stable",
            "Chemistry normal",
        ]
        assert day.assessment == "Perfusion improving"
    finally:
        runtime.shutdown()


def test_successful_structured_saves_automatically_refresh_soap_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn="123456", name="Bella", species="Canine"
        )
        workspace = runtime.window.workspace
        workspace.patient_summary.one_line_summary.setPlainText("Post-operative monitoring")
        assert workspace.patient_summary.save()
        assert "**One Liner:** Post-operative monitoring" in workspace.soap.markdown.toPlainText()

        workspace.charting.examination.setPlainText("BAR and comfortable")
        workspace.charting.treatment.setPlainText("Continue fluids")
        assert workspace.charting.save()
        markdown = workspace.soap.markdown.toPlainText()
        assert "**AM:**\n- BAR and comfortable" in markdown
        assert "**Treatment changes**\n- Continue fluids" in markdown
    finally:
        runtime.shutdown()
