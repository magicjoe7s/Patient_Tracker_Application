"""Interactive hourly digest checklist tests."""

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from icu_patient_tracker.dialogs.reminder_digest_dialog import ReminderDigestDialog
from icu_patient_tracker.domain.enums import ClinicalPriority, TaskCategory
from icu_patient_tracker.services.reminder_service import DigestEntry, HourlyDigest


def test_checking_digest_item_emits_task_identity() -> None:
    application = QApplication.instance() or QApplication([])
    entry = DigestEntry(
        patient_id=uuid4(),
        patient_name="Bella",
        day_number=2,
        task_id=uuid4(),
        title="Recheck perfusion",
        category=TaskCategory.CLINICAL,
        priority=ClinicalPriority.ROUTINE,
    )
    digest = HourlyDigest(
        datetime(2026, 7, 20, 21, tzinfo=UTC),
        (),
        (),
        (),
        (),
        1,
        0,
        open_todos=(entry,),
    )
    dialog = ReminderDigestDialog(digest)
    task_item = dialog.content.item(1)
    received: list[tuple[object, object]] = []
    dialog.task_completed.connect(
        lambda patient_id, task_id: received.append((patient_id, task_id))
    )

    task_item.setCheckState(Qt.CheckState.Checked)
    application.processEvents()

    assert received == [(entry.patient_id, entry.task_id)]
    assert not bool(task_item.flags() & Qt.ItemFlag.ItemIsEnabled)
    dialog.close()
