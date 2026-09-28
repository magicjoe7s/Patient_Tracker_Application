"""Hospital-day input, timeline, navigation, and commit-order tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QMessageBox

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.utils.hospital_day_input import parse_hospital_day_input
from icu_patient_tracker.widgets.day_workspace import format_day_timeline_entry


def make_runtime(tmp_path: Path) -> ApplicationRuntime:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=0,
        )
    )
    runtime = create_runtime(["icu-patient-tracker"], config_path)
    assert runtime.window.patient_panel.create_patient(mrn="A1", name="Bella", species="Canine")
    return runtime


def test_hospital_day_input_accepts_only_approved_syntax() -> None:
    parsed = parse_hospital_day_input(" 2026-07-21 | postop ")
    without_note = parse_hospital_day_input("2026-07-22")

    assert parsed.calendar_date == date(2026, 7, 21)
    assert parsed.label == "postop"
    assert without_note.label is None


@pytest.mark.parametrize(
    "value",
    ["", "07/21/2026", "2026-7-21", "2026-02-30", "2026-07-21 - postop"],
)
def test_hospital_day_input_rejects_ambiguous_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_hospital_day_input(value)


def test_timeline_entry_contains_icu_ordinal_note_and_today_marker() -> None:
    today = date(2026, 7, 21)
    start = datetime.combine(today, time(hour=8), tzinfo=UTC)
    day = HospitalDay(
        patient_id=uuid4(),
        calendar_date=today,
        day_number=2,
        start_at=start,
        label="postop",
    )

    assert format_day_timeline_entry(day, today=today) == "ICU 2 | Jul 21, '26 | postop | Today"


def test_navigation_wraps_and_commits_outgoing_editor_before_selection(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)
    try:
        workspace = runtime.window.workspace
        patient_id = runtime.controller.context.patient_id
        first = runtime.controller.selected_day()
        assert patient_id is not None and first is not None
        assert workspace.day_combo.count() == 1
        assert "ICU 1" in workspace.day_combo.itemText(0)
        assert "Today" in workspace.day_combo.itemText(0)
        second_start = datetime.combine(
            first.calendar_date + timedelta(days=1),
            time(hour=8),
            tzinfo=first.start_at.tzinfo,
        )
        second = workspace.create_day(second_start, "postop")
        assert second is not None
        assert workspace.day_combo.currentIndex() == 1

        workspace.charting.assessment.setPlainText("Outgoing day only")
        workspace.move_day(1)

        assert runtime.controller.context.hospital_day_id == first.id
        stored = runtime.controller.services.days.list(patient_id)
        assert stored[0].assessment == ""
        assert stored[1].assessment == "Outgoing day only"

        workspace.move_day(-1)
        assert runtime.controller.context.hospital_day_id == second.id
        assert workspace.previous_button.isEnabled()
        assert workspace.next_button.isEnabled()
    finally:
        runtime.shutdown()


def test_failed_outgoing_commit_keeps_context_and_timeline_selection(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = make_runtime(tmp_path)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok
    )
    try:
        workspace = runtime.window.workspace
        first = runtime.controller.selected_day()
        assert first is not None
        second_start = datetime.combine(
            first.calendar_date + timedelta(days=1),
            time(hour=8),
            tzinfo=first.start_at.tzinfo,
        )
        second = workspace.create_day(second_start)
        assert second is not None

        def fail_save() -> None:
            raise RuntimeError("synthetic save failure")

        runtime.controller.mark_editor_dirty("forced-failure", fail_save)
        workspace.move_day(-1)

        assert runtime.controller.context.hospital_day_id == second.id
        assert workspace.day_combo.currentData() == second.id

        runtime.controller.mark_editor_dirty("forced-failure", lambda: None)
        assert runtime.controller.flush_pending()
    finally:
        runtime.shutdown()
