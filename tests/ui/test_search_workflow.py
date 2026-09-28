"""Headless Slice 11 census-filter controls."""

from pathlib import Path

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.enums import Acuity, TaskCategory
from icu_patient_tracker.services.search_service import SearchView


def test_live_search_and_six_derived_views_update_the_census(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        panel = runtime.window.patient_panel
        assert panel.create_patient(mrn=None, name="Quiet", species="Canine")
        assert panel.create_patient(mrn=None, name="Urgent", species="Feline")
        patient = runtime.controller.selected_patient()
        day = runtime.controller.selected_day()
        assert patient is not None and day is not None
        runtime.controller.update_day(
            acuity=Acuity.WATCHER,
            label=None,
            treatment_changes="",
            physical_examination="",
            assessment="Searchable assessment phrase",
            clinical_summary="",
        )
        runtime.controller.add_task("Review culture", category=TaskCategory.DIAGNOSTIC)

        assert panel.view_filter.count() == 6
        panel.view_filter.setCurrentIndex(panel.view_filter.findData(SearchView.PENDING_DIAGNOSTIC))
        assert panel.model.rowCount() == 1
        assert str(panel.model.data(panel.model.index(0, 0))).startswith("Urgent\n")

        panel.view_filter.setCurrentIndex(panel.view_filter.findData(SearchView.CRITICAL_WATCHER))
        assert panel.model.rowCount() == 1
        panel.view_filter.setCurrentIndex(panel.view_filter.findData(SearchView.ALL_ACTIVE))
        panel.search.setText("assessment phrase")
        assert panel.model.rowCount() == 1
        assert str(panel.model.data(panel.model.index(0, 0))).startswith("Urgent\n")
    finally:
        runtime.shutdown()
