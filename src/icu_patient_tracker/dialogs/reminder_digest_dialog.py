"""Actionable non-modal hourly reminder digest."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from icu_patient_tracker.services.reminder_service import DigestEntry, HourlyDigest


class ReminderDigestDialog(QDialog):
    """Display and complete current clinical work from the hourly popup."""

    snoozed = Signal()
    task_completed = Signal(object, object)

    def __init__(self, digest: HourlyDigest, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Hourly clinical digest")
        self.resize(540, 480)
        summary = QLabel(
            f"Open To Do / POCUS: {digest.open_todo_count}    "
            f"Open diagnostics: {digest.open_diagnostic_count}"
        )
        self.content = QListWidget()
        self.content.setObjectName("hourlyDigestContent")
        self._populate(digest)
        self.content.itemChanged.connect(self._item_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.snooze_button = buttons.addButton(
            "Snooze 5 minutes", QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.rejected.connect(self.close)
        self.snooze_button.clicked.connect(self._snooze)
        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.content)
        layout.addWidget(buttons)

    def _snooze(self) -> None:
        self.snoozed.emit()
        self.close()

    def _populate(self, digest: HourlyDigest) -> None:
        sections = (
            ("To Do / POCUS", digest.open_todos),
            ("Pending diagnostics", digest.pending_diagnostics),
            ("Long-term follow-up", digest.follow_up),
            ("9 PM housekeeping", digest.housekeeping),
        )
        seen: set[tuple[object, object]] = set()
        for heading, entries in sections:
            unique = [
                entry
                for entry in entries
                if (entry.patient_id, entry.task_id) not in seen
            ]
            if not unique:
                continue
            heading_item = QListWidgetItem(heading)
            heading_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.content.addItem(heading_item)
            for entry in unique:
                seen.add((entry.patient_id, entry.task_id))
                item = QListWidgetItem(self._entry_text(entry))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, (entry.patient_id, entry.task_id))
                self.content.addItem(item)
        if self.content.count() == 0:
            empty = QListWidgetItem("No actionable items.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.content.addItem(empty)

    def _item_changed(self, item: QListWidgetItem) -> None:
        identity = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() is not Qt.CheckState.Checked or not isinstance(identity, tuple):
            return
        patient_id, task_id = identity
        item.setData(Qt.ItemDataRole.UserRole, None)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        self.task_completed.emit(patient_id, task_id)

    @staticmethod
    def _entry_text(entry: DigestEntry) -> str:
        return f"{entry.patient_name} — Day {entry.day_number}: {entry.title}"
