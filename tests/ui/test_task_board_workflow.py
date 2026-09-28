"""Four-pane task board and focused diagnostics integration tests."""

from datetime import timedelta
from pathlib import Path

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.enums import TaskCategory, TaskStatus


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


def test_main_window_opens_four_derived_task_panes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        patient = runtime.controller.services.patients.create(name="Bella", species="Canine")
        day = patient.hospital_days[0]
        for category in (
            TaskCategory.CLINICAL,
            TaskCategory.POCUS,
            TaskCategory.DIAGNOSTIC,
            TaskCategory.HOUSEKEEPING,
        ):
            runtime.controller.services.tasks.create(
                patient.id,
                day.id,
                title=category.value,
                category=category,
            )

        runtime.window._show_task_board()
        board = runtime.window._task_board_dialog

        assert board is not None and board.isVisible()
        assert set(board.panes) == {
            TaskCategory.CLINICAL,
            TaskCategory.POCUS,
            TaskCategory.DIAGNOSTIC,
            TaskCategory.HOUSEKEEPING,
        }
        assert all(pane.model.rowCount() == 1 for pane in board.panes.values())
        assert all(toggle.isChecked() for toggle in board.category_toggles.values())
        board.category_toggles[TaskCategory.POCUS].setChecked(False)
        assert board.panes[TaskCategory.POCUS].isHidden()
        assert not board.panes[TaskCategory.CLINICAL].isHidden()
        assert "task_board" in runtime.window.actions_by_name
        assert "pending_diagnostics" in runtime.window.actions_by_name
    finally:
        runtime.shutdown()


def test_board_mutation_refreshes_all_task_surfaces_and_activation_navigates(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        first = runtime.controller.services.patients.create(name="First", species="Canine")
        second = runtime.controller.services.patients.create(name="Second", species="Feline")
        first_day = first.hospital_days[0]
        second_day = runtime.controller.services.days.create(
            first.id,
            start_at=first_day.start_at + timedelta(days=1),
        )
        runtime.controller.services.tasks.create(
            first.id,
            second_day.id,
            title="Call owner",
            category=TaskCategory.CLINICAL,
        )
        assert runtime.controller.select_patient(second.id)
        runtime.window._show_task_board()
        board = runtime.window._task_board_dialog
        assert board is not None
        pane = board.panes[TaskCategory.CLINICAL]
        pane.list_view.setCurrentIndex(pane.model.index(0, 0))
        row = pane.selected_row()
        assert row is not None

        pane._toggle()

        assert pane.model.rowCount() == 0
        stored = runtime.controller.services.tasks.list_for_day(first.id, second_day.id)
        assert stored[0].status is TaskStatus.COMPLETED

        pane.hide_completed.setChecked(False)
        runtime.window.workspace.tasks.hide_completed.setChecked(False)
        pane.list_view.setCurrentIndex(pane.model.index(0, 0))
        pane._navigate()

        assert runtime.controller.context.patient_id == first.id
        assert runtime.controller.context.hospital_day_id == second_day.id
        assert not board.isVisible()
        assert runtime.window.workspace.tasks.model.rowCount() == 1
    finally:
        runtime.shutdown()


def test_pending_diagnostics_is_selected_day_focused_and_event_refreshed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        patient = runtime.controller.services.patients.create(name="Bella", species="Canine")
        day = patient.hospital_days[0]
        assert runtime.controller.select_patient(patient.id)
        runtime.controller.services.tasks.create(
            patient.id,
            day.id,
            title="Recheck lactate",
            category=TaskCategory.DIAGNOSTIC,
        )
        runtime.controller.services.tasks.create(
            patient.id,
            day.id,
            title="Call owner",
            category=TaskCategory.CLINICAL,
        )
        runtime.window._show_pending_diagnostics()
        dialog = runtime.window._pending_diagnostics_dialog
        assert dialog is not None
        assert dialog.model.rowCount() == 1
        assert "Bella" in dialog.patient_label.text()

        runtime.controller.services.tasks.create(
            patient.id,
            day.id,
            title="Recheck PCV",
            category=TaskCategory.DIAGNOSTIC,
        )
        runtime.application.processEvents()

        assert dialog.model.rowCount() == 2
    finally:
        runtime.shutdown()


def test_double_clicking_board_diagnostic_opens_capture_and_restores_board(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        patient = runtime.controller.services.patients.create(name="Bella", species="Canine")
        day = patient.hospital_days[0]
        task = runtime.controller.services.tasks.create(
            patient.id,
            day.id,
            title="CBC",
            category=TaskCategory.DIAGNOSTIC,
        )
        runtime.window._show_task_board()
        board = runtime.window._task_board_dialog
        assert board is not None
        pane = board.panes[TaskCategory.DIAGNOSTIC]
        pane.list_view.setCurrentIndex(pane.model.index_for(task.id))

        pane._navigate()

        dialog = runtime.window._diagnostic_result_dialog
        assert dialog is not None and dialog.isVisible()
        assert dialog.current_task_id() == task.id
        assert board.isMinimized()

        dialog.hide()
        runtime.application.processEvents()
        assert not board.isMinimized()
        assert board.isVisible()
    finally:
        runtime.shutdown()
