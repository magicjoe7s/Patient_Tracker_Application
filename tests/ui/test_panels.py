"""Focused stable-identity and panel interaction tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    ClinicalPriority,
    CodeStatus,
    ProblemStatus,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.services.search_service import SearchSort

START = datetime(2026, 7, 20, 8, tzinfo=UTC)


def make_selected_runtime(tmp_path: Path) -> ApplicationRuntime:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=0.5,
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    runtime.window.patient_panel.create_patient(mrn="A1", name="Bella", species="Canine")
    return runtime


def test_patient_model_preserves_uuid_selection_after_update(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        panel = runtime.window.patient_panel
        panel.create_patient(mrn="A2", name="Bella", species="Feline")
        first_patient = runtime.controller.services.patients.get_by_mrn("A1")
        first = panel.model.index_for(first_patient.id)
        panel.list_view.clicked.emit(first)
        assert runtime.controller.rename_patient(first_patient.id, "Bella Renamed") is not None
        panel.refresh()
        assert panel.model.identifier(panel.list_view.currentIndex()) == first_patient.id
        assert (
            runtime.controller.change_patient_status(first_patient.id, AdmissionStatus.DISCHARGED)
            is not None
        )
    finally:
        runtime.shutdown()


def test_patient_summary_and_daily_charting_remain_in_their_own_contexts(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        workspace = runtime.window.workspace
        first_id = runtime.controller.context.patient_id
        first_day_id = runtime.controller.context.hospital_day_id
        assert first_id is not None
        assert first_day_id is not None

        summary = workspace.patient_summary
        summary.name.setText("Bella Rose")
        summary.acuity.setCurrentIndex(summary.acuity.findData(Acuity.CRITICAL))
        summary.code_status.setCurrentIndex(summary.code_status.findData(CodeStatus.DVM_DISCRETION))
        summary.one_line_summary.setPlainText("Post-operative monitoring")
        workspace.charting.summary.setPlainText("Comfortable overnight")

        second = runtime.controller.create_patient(name="Milo", species="Feline")
        assert second is not None
        assert runtime.controller.select_patient(second.id)
        assert workspace.patient_summary.name.text() == "Milo"
        assert workspace.patient_summary.one_line_summary.toPlainText() == ""
        assert workspace.charting.summary.toPlainText() == ""

        assert runtime.controller.select_patient(first_id)
        assert runtime.controller.context.hospital_day_id == first_day_id
        assert workspace.patient_summary.name.text() == "Bella Rose"
        assert CodeStatus(str(workspace.patient_summary.code_status.currentData())) is (
            CodeStatus.DVM_DISCRETION
        )
        assert workspace.patient_summary.one_line_summary.toPlainText() == (
            "Post-operative monitoring"
        )
        assert workspace.charting.diagnostics.toPlainText() == "- [ ] Comfortable overnight"
    finally:
        runtime.shutdown()


def test_committed_events_refresh_clean_summary_and_charting_views(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        patient_id = runtime.controller.context.patient_id
        day_id = runtime.controller.context.hospital_day_id
        assert patient_id is not None
        assert day_id is not None

        runtime.controller.services.patients.update_profile(
            patient_id,
            name="Bella Updated",
            species="Canine",
            mrn="A1",
            one_line_summary="External patient update",
            code_status=CodeStatus.FULL_CODE,
            blood_type=None,
            acuity=Acuity.WATCHER,
        )
        assert runtime.window.workspace.patient_summary.name.text() == "Bella Updated"
        assert (
            runtime.window.workspace.patient_summary.one_line_summary.toPlainText()
            == "External patient update"
        )

        runtime.controller.services.days.update(
            patient_id,
            day_id,
            assessment="External day update",
        )
        assert runtime.window.workspace.charting.assessment.toPlainText() == "External day update"
    finally:
        runtime.shutdown()


def test_empty_query_census_honors_sort_modes(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        alfie = runtime.controller.services.patients.create(
            name="Alfie", species="Feline", acuity=Acuity.STABLE
        )
        runtime.controller.services.patients.create(
            name="Zoe", species="Canine", acuity=Acuity.CRITICAL
        )
        runtime.controller.services.patients.change_status(alfie.id, AdmissionStatus.DISCHARGED)

        by_name = runtime.controller.patients(status=None, sort=SearchSort.NAME)
        by_acuity = runtime.controller.patients(status=None, sort=SearchSort.ACUITY)
        by_status = runtime.controller.patients(status=None, sort=SearchSort.STATUS)

        assert [patient.name for patient in by_name] == ["Alfie", "Bella", "Zoe"]
        assert [patient.name for patient in by_acuity] == ["Zoe", "Alfie", "Bella"]
        assert [patient.admission_status.value for patient in by_status] == sorted(
            patient.admission_status.value for patient in by_status
        )
    finally:
        runtime.shutdown()


def test_patient_details_and_readmission_are_available_from_census(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = make_selected_runtime(tmp_path)
    panel = runtime.window.patient_panel
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("Feline", True))
    try:
        patient_id = runtime.controller.context.patient_id
        assert patient_id is not None

        panel._prompt_details()
        corrected = runtime.controller.services.patients.get(patient_id)
        assert corrected.id == patient_id
        assert corrected.mrn == "A1"
        assert corrected.species == "Feline"

        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
        )
        panel._confirm_archive()
        assert (
            runtime.controller.services.patients.get(patient_id).admission_status
            is AdmissionStatus.ADMITTED
        )
        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )
        panel._confirm_archive()
        assert (
            runtime.controller.services.patients.get(patient_id).admission_status
            is AdmissionStatus.ARCHIVED
        )
        panel.status_filter.setCurrentIndex(1)
        panel.refresh()
        panel.list_view.setCurrentIndex(panel.model.index_for(patient_id))
        assert panel.readmit_button.isEnabled()
        panel._readmit()
        assert (
            runtime.controller.services.patients.get(patient_id).admission_status
            is AdmissionStatus.ADMITTED
        )
    finally:
        runtime.shutdown()


def test_death_disposition_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    runtime = make_selected_runtime(tmp_path)
    panel = runtime.window.patient_panel
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("Death", True))
    try:
        patient_id = runtime.controller.context.patient_id
        assert patient_id is not None
        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
        )
        panel._prompt_status()
        assert (
            runtime.controller.services.patients.get(patient_id).admission_status
            is AdmissionStatus.ADMITTED
        )

        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )
        panel._prompt_status()
        assert (
            runtime.controller.services.patients.get(patient_id).admission_status
            is AdmissionStatus.DECEASED
        )
    finally:
        runtime.shutdown()


def test_manual_census_controls_reorder_by_uuid(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    panel = runtime.window.patient_panel
    try:
        second = runtime.controller.services.patients.create(name="Second", species="Canine")
        third = runtime.controller.services.patients.create(name="Third", species="Feline")
        panel.refresh()
        assert panel.sort_mode.currentData() == SearchSort.MANUAL
        third_index = panel.model.index_for(third.id)
        panel.list_view.setCurrentIndex(third_index)
        panel.list_view.clicked.emit(third_index)
        assert panel.move_up_button.isEnabled()

        panel._move(-1)

        assert [
            patient.id
            for patient in runtime.controller.services.patients.list(
                status=AdmissionStatus.ADMITTED
            )
        ] == [
            runtime.controller.services.patients.get_by_mrn("A1").id,
            third.id,
            second.id,
        ]
    finally:
        runtime.shutdown()


def test_permanent_delete_requires_archived_patient_and_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = make_selected_runtime(tmp_path)
    panel = runtime.window.patient_panel
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    try:
        patient_id = runtime.controller.context.patient_id
        assert patient_id is not None
        panel._confirm_archive()
        panel.status_filter.setCurrentIndex(1)
        panel.refresh()
        panel.list_view.setCurrentIndex(panel.model.index_for(patient_id))
        assert panel.purge_button.isEnabled()

        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.No
        )
        panel._confirm_purge()
        assert runtime.controller.services.patients.get(patient_id).id == patient_id

        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )
        panel._confirm_purge()
        assert runtime.controller.services.patients.list() == ()
        assert runtime.controller.context.patient_id is None
    finally:
        runtime.shutdown()


def test_duplicate_day_rejection_is_presented_without_cross_write(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = make_selected_runtime(tmp_path)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    runtime.controller.error_raised.connect(
        lambda title, message: messages.append((title, message))
    )
    try:
        original_id = runtime.controller.context.hospital_day_id
        selected_day = runtime.controller.selected_day()
        assert selected_day is not None
        assert runtime.window.workspace.create_day(selected_day.start_at) is None
        assert runtime.controller.context.hospital_day_id == original_id
        assert any("already exists" in message for _, message in messages)
    finally:
        runtime.shutdown()


def test_problem_task_and_device_panels_mutate_stable_records(tmp_path: Path, monkeypatch) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        workspace = runtime.window.workspace
        assert workspace.problems.add_problem("Anemia")
        assert workspace.problems.add_problem("Hypotension")
        second_id = workspace.problems.selected_id()
        workspace.problems._move(-1)
        assert (
            workspace.problems.model.identifier(workspace.problems.model.index(0, 0)) == second_id
        )

        assert workspace.tasks.add_task("Recheck PCV")
        task_index = workspace.tasks.model.index(0, 0)
        workspace.tasks.list_view.setCurrentIndex(task_index)
        workspace.tasks._toggle()
        assert workspace.tasks.model.rowCount() == 0
        workspace.tasks.hide_completed.setChecked(False)
        workspace.tasks.list_view.setCurrentIndex(workspace.tasks.model.index(0, 0))
        workspace.tasks._toggle()
        assert "Recheck PCV" in str(workspace.tasks.model.data(workspace.tasks.model.index(0, 0)))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        workspace.tasks._confirm_delete()
        assert workspace.tasks.model.rowCount() == 1

        workspace.instrumentation.editor.setPlainText(
            "Foley catheter — urinary bladder\nNG tube — left nare"
        )
        assert workspace.instrumentation.save()
        assert len(runtime.controller.devices()) == 2
        workspace.instrumentation.editor.setPlainText("NG tube — left nare")
        assert workspace.instrumentation.save()
        assert [device.anatomical_location for device in runtime.controller.devices()] == [
            "NG tube — left nare"
        ]
    finally:
        runtime.shutdown()


def test_problem_panel_forward_workflow_preserves_earlier_day(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        workspace = runtime.window.workspace
        patient_id = runtime.controller.context.patient_id
        first_day = runtime.controller.selected_day()
        assert patient_id is not None
        assert first_day is not None
        assert workspace.problems.add_problem("Anemia")
        original = runtime.controller.problems()[0]

        second_day = runtime.controller.create_day(first_day.start_at + timedelta(days=1))
        assert second_day is not None
        third_day = runtime.controller.create_day(first_day.start_at + timedelta(days=2))
        assert third_day is not None
        assert second_day.problem_list.problems[0].lineage_id == original.lineage_id
        assert third_day.problem_list.problems[0].occurrence_number == 3

        assert runtime.controller.select_day(second_day.id)
        second_problem = runtime.controller.problems()[0]
        assert runtime.controller.update_problem(
            second_problem.id,
            title="Regenerative anemia",
            priority=second_problem.priority,
            assessment="Improving",
        )
        assert runtime.controller.set_problem_status(second_problem.id, ProblemStatus.RESOLVED)

        stored_days = runtime.controller.services.days.list(patient_id)
        assert stored_days[0].problem_list.problems[0].title == "Anemia"
        assert stored_days[0].problem_list.problems[0].status is ProblemStatus.ACTIVE
        assert [day.problem_list.problems[0].title for day in stored_days[1:]] == [
            "Regenerative anemia",
            "Regenerative anemia",
        ]
        assert [day.problem_list.problems[0].status for day in stored_days[1:]] == [
            ProblemStatus.RESOLVED,
            ProblemStatus.RESOLVED,
        ]

        fourth_day = runtime.controller.create_day(first_day.start_at + timedelta(days=3))
        assert fourth_day is not None
        assert fourth_day.problem_list.problems == ()
    finally:
        runtime.shutdown()


def test_problem_list_autosave_preserves_focused_text_cursor_and_selection(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        summary = runtime.window.workspace.patient_summary
        assert runtime.window.workspace.problems.add_problem("Anemia")
        runtime.window.show()
        summary.running_problems.setFocus()
        runtime.application.processEvents()
        assert summary.running_problems.hasFocus()

        draft = "- Anemia\nNew respiratory concern"
        summary.running_problems.setPlainText(draft)
        cursor = summary.running_problems.textCursor()
        selection_start = draft.index("respiratory")
        cursor.setPosition(selection_start)
        cursor.setPosition(selection_start + len("respiratory"), QTextCursor.MoveMode.KeepAnchor)
        summary.running_problems.setTextCursor(cursor)

        assert runtime.controller.flush_pending()

        saved_cursor = summary.running_problems.textCursor()
        assert summary.running_problems.toPlainText() == draft
        assert saved_cursor.selectionStart() == selection_start
        assert saved_cursor.selectionEnd() == selection_start + len("respiratory")
        assert [problem.title for problem in runtime.controller.problems()] == [
            "Anemia",
            "New respiratory concern",
        ]
    finally:
        runtime.shutdown()


def test_numbered_problem_editor_reorders_details_forward_and_refreshes_soap(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        problems = runtime.window.workspace.problems
        assert problems.add_problem("Anemia", description="PCV 22%")
        assert problems.add_problem("Hypotension", description="Fluid responsive")
        summary = runtime.window.workspace.patient_summary
        summary.running_problems.setPlainText(
            "1. Hypotension\n"
            "   • MAP now 75\n"
            "2. Anemia\n"
            "   • PCV stable at 24%\n"
            "   • Recheck tomorrow"
        )

        assert summary.apply_problem_list()

        stored = runtime.controller.problems()
        assert [problem.title for problem in stored] == ["Hypotension", "Anemia"]
        assert stored[0].description == "MAP now 75"
        assert stored[1].description == "PCV stable at 24%\nRecheck tomorrow"
        summary.refresh_running_problems(force=True)
        assert summary.running_problems.toPlainText().startswith("1. Hypotension")

        soap = runtime.window.workspace.soap
        soap.refresh(force=True)
        soap.refresh_mapped(("problem_list",))
        markdown = soap.markdown.toPlainText()
        assert "1. Hypotension\n   - MAP now 75" in markdown
        assert "2. Anemia\n   - PCV stable at 24%\n   - Recheck tomorrow" in markdown
    finally:
        runtime.shutdown()


def test_patient_one_liner_and_problem_list_sync_bidirectionally_with_soap(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        window = runtime.window
        soap = window.workspace.soap
        soap.refresh(force=True)
        summary = window.workspace.patient_summary

        summary.one_line_summary.setPlainText("Stable after surgery")
        assert summary.save()
        assert "**One Liner:** Stable after surgery" in soap.markdown.toPlainText()

        summary.running_problems.setPlainText("1. Anemia\n2. Hypotension")
        assert summary.apply_problem_list()
        assert "1. Anemia" in soap.markdown.toPlainText()
        assert "2. Hypotension" in soap.markdown.toPlainText()

        edited = (
            soap.markdown.toPlainText()
            .replace("**One Liner:** Stable after surgery", "**One Liner:** Improving")
            .replace(
                "1. Anemia\n2. Hypotension",
                "1. Hypotension\n2. Respiratory concern",
            )
        )
        soap.markdown.setPlainText(edited)
        assert soap.save()
        assert runtime.controller.selected_patient().one_line_summary == "Improving"
        assert [problem.title for problem in runtime.controller.problems()] == [
            "Hypotension",
            "Respiratory concern",
        ]
        assert summary.one_line_summary.toPlainText() == "Improving"
        assert "1. Hypotension" in summary.running_problems.toPlainText()
        assert "2. Respiratory concern" in summary.running_problems.toPlainText()
    finally:
        runtime.shutdown()


def test_patient_problem_text_autosaves_numbered_details_directly_into_soap(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        window = runtime.window
        window.show()
        soap = window.workspace.soap
        soap.refresh(force=True)
        editor = window.workspace.patient_summary.running_problems
        editor.setFocus()
        editor.setPlainText(
            "1. Anemia\n   - PCV 22%; regenerative\n2. Hypotension\n   • Fluid responsive"
        )

        QTest.qWait(1_200)
        runtime.application.processEvents()

        markdown = soap.markdown.toPlainText()
        assert "1. Anemia\n   - PCV 22%; regenerative" in markdown
        assert "2. Hypotension\n   - Fluid responsive" in markdown
        stored = runtime.controller.problems()
        assert [(problem.title, problem.description) for problem in stored] == [
            ("Anemia", "PCV 22%; regenerative"),
            ("Hypotension", "Fluid responsive"),
        ]

        editor.setPlainText("1. Hypotension\n   - MAP stable")
        QTest.qWait(1_200)
        runtime.application.processEvents()
        assert [problem.title for problem in runtime.controller.problems()] == ["Hypotension"]
        markdown = soap.markdown.toPlainText()
        assert "1. Hypotension\n   - MAP stable" in markdown
        assert "Anemia" not in markdown
    finally:
        runtime.shutdown()


def test_free_text_devices_sync_bidirectionally_with_soap_instrumentation(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        window = runtime.window
        soap = window.workspace.soap
        soap.refresh(force=True)
        devices = window.workspace.instrumentation

        devices.editor.setPlainText("Foley catheter — placed 8/3\nNG tube — left nare")
        assert devices.save()
        markdown = soap.markdown.toPlainText()
        assert "**instrumentation:**\n- Foley catheter — placed 8/3" in markdown
        assert "- NG tube — left nare" in markdown

        edited = markdown.replace(
            "- Foley catheter — placed 8/3\n- NG tube — left nare",
            "- NG tube — right nare\n- Jackson-Pratt drain — 12 mL overnight",
        )
        soap.markdown.setPlainText(edited)
        assert soap.save()
        assert devices.editor.toPlainText() == (
            "NG tube — right nare\nJackson-Pratt drain — 12 mL overnight"
        )
        assert [device.anatomical_location for device in runtime.controller.devices()] == [
            "NG tube — right nare",
            "Jackson-Pratt drain — 12 mL overnight",
        ]
    finally:
        runtime.shutdown()


def test_autosave_preserves_cursor_selection_and_focus_across_text_editors(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        window = runtime.window
        window.show()
        runtime.application.processEvents()
        editors = (
            (window.workspace.patient_summary.one_line_summary, "Summary draft in progress"),
            (window.workspace.charting.examination, "Examination draft in progress"),
            (window.workspace.soap.markdown, "SOAP draft in progress"),
            (window.workspace.sandbox.editor, "Sandbox draft in progress"),
        )

        for editor, draft in editors:
            editor.setPlainText(draft)
            editor.setFocus()
            runtime.application.processEvents()
            cursor = editor.textCursor()
            cursor.setPosition(3)
            cursor.setPosition(11, QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)

            assert runtime.controller.flush_pending()
            runtime.application.processEvents()

            saved_cursor = editor.textCursor()
            if window.isActiveWindow():
                assert editor.hasFocus()
            assert editor.toPlainText() == draft
            assert saved_cursor.selectionStart() == 3
            assert saved_cursor.selectionEnd() == 11

        label = window.workspace.charting.label
        label.setText("Bella Autosave")
        label.setFocus()
        label.setSelection(2, 6)
        assert runtime.controller.flush_pending()
        runtime.application.processEvents()
        if window.isActiveWindow() and label.isVisible():
            assert label.hasFocus()
        assert label.text() == "Bella Autosave"
        assert label.selectionStart() == 2
        assert label.selectedText() == "lla Au"
    finally:
        runtime.shutdown()


def test_soap_cursor_does_not_jump_when_typing_pauses_for_autosave(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        window = runtime.window
        window.show()
        runtime.application.processEvents()
        editor = window.workspace.soap.markdown
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.setPosition(editor.toPlainText().find("**One Liner:**") + len("**One Liner:** "))
        editor.setTextCursor(cursor)
        QTest.keyClicks(editor, "Patient remains stable")
        expected_position = editor.textCursor().position()
        expected_scroll = editor.verticalScrollBar().value()

        QTest.qWait(1_200)
        runtime.application.processEvents()

        assert editor.hasFocus()
        assert editor.textCursor().position() == expected_position
        assert editor.textCursor().anchor() == expected_position
        assert editor.verticalScrollBar().value() == expected_scroll
    finally:
        runtime.shutdown()


def test_task_panel_parses_routes_and_persists_category_preferences(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        panel = runtime.window.workspace.tasks
        assert panel.add_task("!! POCUS lung scan | b:overnight | r:60m | nocarry")
        tasks = runtime.controller.tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.category is TaskCategory.POCUS
        assert task.priority is ClinicalPriority.CRITICAL
        assert task.bucket is TaskBucket.OVERNIGHT
        assert not task.carry_forward
        assert task.reminder is not None
        assert task.reminder.interval_minutes == 60
        assert panel.category_toggles[TaskCategory.POCUS].isChecked()
        assert panel.model.rowCount() == 1

        assert panel.add_task("Call owner", TaskCategory.CLINICAL)
        assert panel.add_task("CBC", TaskCategory.DIAGNOSTIC)
        assert panel.add_task("Round off", TaskCategory.HOUSEKEEPING)
        assert panel.model.rowCount() == 4
        panel.category_toggles[TaskCategory.DIAGNOSTIC].setChecked(False)
        assert panel.model.rowCount() == 3
        panel.category_toggles[TaskCategory.DIAGNOSTIC].setChecked(True)
        assert panel.model.rowCount() == 4

        panel.hide_completed.setChecked(False)
        assert not panel.hide_completed.isChecked()
        assert all(toggle.isChecked() for toggle in panel.category_toggles.values())

        config = runtime.controller.settings()
        assert config is not None
        preferences = config.user_preferences["task_hide_completed"]
        assert isinstance(preferences, dict)
        assert preferences[TaskCategory.CLINICAL.value] is False
        assert preferences.get(TaskCategory.POCUS.value, True) is True
    finally:
        runtime.shutdown()


def test_charting_diagnostic_results_are_editable_and_complete_on_save(
    tmp_path: Path,
) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        charting = runtime.window.workspace.charting
        task = runtime.controller.add_task("CBC", category=TaskCategory.DIAGNOSTIC)
        assert task is not None
        charting.refresh_diagnostic_results()
        assert charting.diagnostics.toPlainText() == "- [ ] CBC"

        charting.diagnostics.setPlainText("CBC: Preliminary mild anemia")
        assert charting.save()
        stored = runtime.controller.diagnostic_tasks_for(task.patient_id, task.hospital_day_id)[0]
        assert stored.status is TaskStatus.COMPLETED
        assert stored.diagnostic_result is not None
        assert stored.diagnostic_result.result_text == "Preliminary mild anemia"

        charting.diagnostics.setPlainText("[x] CBC: Mild anemia; platelets adequate")
        assert charting.save()
        stored = runtime.controller.diagnostic_tasks_for(task.patient_id, task.hospital_day_id)[0]
        assert stored.status is TaskStatus.COMPLETED
        assert stored.diagnostic_result is not None
        assert stored.diagnostic_result.result_text == "Mild anemia; platelets adequate"
    finally:
        runtime.shutdown()


def test_targeted_soap_refresh_preserves_unrelated_editor_sections(tmp_path: Path) -> None:
    runtime = make_selected_runtime(tmp_path)
    try:
        workspace = runtime.window.workspace
        workspace.charting.examination.setPlainText("Normal examination")
        assert runtime.controller.flush_pending()
        soap = workspace.soap
        assert soap.save()
        custom = soap.markdown.toPlainText().replace(
            "## **Recommendations**",
            "Custom unrelated note\n\n## **Recommendations**",
        )
        soap.markdown.setPlainText(custom)
        assert runtime.controller.flush_pending()
        soap.refresh_mapped(("physical_examination",))
        refreshed = soap.markdown.toPlainText()
        assert "Normal examination" in refreshed
        assert "Custom unrelated note" in refreshed
        assert refreshed[refreshed.index("**PM:**") :] == custom[custom.index("**PM:**") :]
    finally:
        runtime.shutdown()


def test_settings_theme_applies_immediately_and_invalid_update_is_retained(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = make_selected_runtime(tmp_path)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    try:
        assert runtime.controller.update_settings(theme="light") is not None
        runtime.application.processEvents()
        assert "#f2f4f7" in runtime.application.styleSheet()
        before = runtime.controller.settings()
        assert runtime.controller.update_settings(backup_retention_count=0) is None
        after = runtime.controller.settings()
        assert before is not None and after is not None
        assert after.backup_retention_count == before.backup_retention_count
    finally:
        runtime.shutdown()
