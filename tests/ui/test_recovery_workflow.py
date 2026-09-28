"""Headless Slice 16 recovery and reviewed-restore integration tests."""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def _runtime(tmp_path: Path) -> ApplicationRuntime:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=60,
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    runtime.application.processEvents()
    return runtime


def _simulate_interruption(runtime: ApplicationRuntime) -> None:
    """Release process resources without invoking the normal save-on-close path."""
    runtime.autosave.stop()
    runtime.reminders.stop()
    runtime.recovery.stop()
    runtime.events.close()
    runtime.database.dispose()
    runtime.window.hide()
    runtime._is_shutdown = True


def test_interrupted_charting_draft_loads_unsaved_and_saves_only_after_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_runtime = _runtime(tmp_path)
    assert first_runtime.window.patient_panel.create_patient(
        mrn=None, name="Bella", species="Canine"
    )
    first_runtime.window.workspace.charting.assessment.setPlainText("Unsaved overnight change")
    assert first_runtime.controller.services.recovery.flush()
    recovery_path = tmp_path / "recovery.json"
    assert recovery_path.exists()
    _simulate_interruption(first_runtime)

    second_runtime = create_runtime(["icu-patient-tracker"], tmp_path / "config.json")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        second_runtime.application.processEvents()
        charting = second_runtime.window.workspace.charting

        assert charting.assessment.toPlainText() == "Unsaved overnight change"
        assert second_runtime.controller.context.is_dirty
        selected = second_runtime.controller.selected_day()
        assert selected is not None and selected.assessment == ""

        assert second_runtime.controller.flush_pending()
        selected = second_runtime.controller.selected_day()
        assert selected is not None and selected.assessment == "Unsaved overnight change"
        assert not recovery_path.exists()
        assert (tmp_path / "recovery.json.bak").exists()
    finally:
        second_runtime.shutdown()


def test_reviewed_backup_restores_and_reopens_live_services(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        patients = runtime.controller.services.patients
        original = patients.create(name="In Backup", species="Canine")
        backup = runtime.controller.create_backup()
        assert backup is not None
        later = patients.create(name="Added Later", species="Feline")
        descriptor = runtime.controller.inspect_backup(backup)
        assert descriptor is not None

        safety_backup = runtime.controller.restore_backup(descriptor)

        assert safety_backup is not None and safety_backup.exists()
        assert patients.get(original.id).name == "In Backup"
        assert all(patient.id != later.id for patient in patients.list())
        assert runtime.controller.context.patient_id is None
        assert "pre-restore safety backup" in runtime.controller.context.save_status
    finally:
        runtime.shutdown()


def test_changed_canonical_record_blocks_silent_draft_application(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_runtime = _runtime(tmp_path)
    assert first_runtime.window.patient_panel.create_patient(
        mrn=None, name="Bella", species="Canine"
    )
    patient_id = first_runtime.controller.context.patient_id
    day_id = first_runtime.controller.context.hospital_day_id
    assert patient_id is not None and day_id is not None
    first_runtime.window.workspace.charting.assessment.setPlainText("Older unsaved draft")
    assert first_runtime.controller.services.recovery.flush()
    first_runtime.controller.services.days.update(
        patient_id,
        day_id,
        assessment="Newer committed value",
    )
    _simulate_interruption(first_runtime)

    second_runtime = create_runtime(["icu-patient-tracker"], tmp_path / "config.json")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    try:
        second_runtime.application.processEvents()

        assert (
            second_runtime.window.workspace.charting.assessment.toPlainText()
            == "Newer committed value"
        )
        assert not second_runtime.controller.context.is_dirty
        assert (tmp_path / "recovery.json").exists()
    finally:
        second_runtime.controller.discard_recovery()
        second_runtime.shutdown()


def test_restore_ui_requires_confirmation_before_database_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        patients = runtime.controller.services.patients
        original = patients.create(name="In Backup", species="Canine")
        backup = runtime.controller.create_backup()
        assert backup is not None
        later = patients.create(name="Keep Me", species="Feline")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(backup), "SQLite backups (*.sqlite3)"),
        )
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )

        runtime.window._restore_backup()

        assert patients.get(original.id).name == "In Backup"
        assert patients.get(later.id).name == "Keep Me"
        assert "create_backup" in runtime.window.actions_by_name
        assert "restore_backup" in runtime.window.actions_by_name
        assert runtime.window._registry.parse("backup").action_name == "create_backup"
    finally:
        runtime.shutdown()
