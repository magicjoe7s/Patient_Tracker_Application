"""Resizable, read-only current-state analytics report."""

from __future__ import annotations

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.services.analytics_service import (
    AnalyticsSnapshot,
    format_analytics_report,
)
from icu_patient_tracker.ui.controller import PresentationController


class AnalyticsDialog(QDialog):
    """Display one replaceable service snapshot without owning aggregate state."""

    def __init__(
        self,
        controller: PresentationController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._snapshot: AnalyticsSnapshot | None = None
        self.setWindowTitle("ICU Tracker Analytics")
        self.setMinimumSize(620, 420)
        self.resize(790, 520)
        self.status_label = QLabel("Not yet calculated")
        self.report = QPlainTextEdit()
        self.report.setObjectName("analyticsReport")
        self.report.setAccessibleName("Read-only ICU analytics report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.refresh_button = QPushButton("Refresh")
        self.copy_button = QPushButton("Copy")
        self.close_button = QPushButton("Close")
        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.close_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.report, 1)
        layout.addLayout(buttons)
        self.refresh_button.clicked.connect(self.refresh)
        self.copy_button.clicked.connect(self.copy_report)
        self.close_button.clicked.connect(self.hide)
        self.copy_button.setEnabled(False)

    @property
    def snapshot(self) -> AnalyticsSnapshot | None:
        return self._snapshot

    def refresh(self) -> None:
        snapshot = self._controller.analytics_snapshot()
        if snapshot is None:
            self.status_label.setText("Analytics refresh failed")
            return
        self._snapshot = snapshot
        self.report.setPlainText(format_analytics_report(snapshot))
        self.status_label.setText(f"Generated {snapshot.generated_at:%Y-%m-%d %H:%M}")
        self.copy_button.setEnabled(True)

    def copy_report(self) -> bool:
        if self._snapshot is None:
            return False
        return self._controller.copy_analytics(self._snapshot)

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)
