"""Qt timer and platform-notification boundary for reminder services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from icu_patient_tracker.services.reminder_service import HourlyDigest, ReminderService


class NotificationSink(Protocol):
    """Small boundary around platform notification delivery."""

    def show(self, title: str, message: str) -> bool:
        """Show a notification and report whether platform delivery was requested."""


class QtSystemTrayNotificationSink:
    """Best-effort OS notification implementation backed by Qt."""

    def __init__(self, tray_icon: QSystemTrayIcon | None = None) -> None:
        self._tray_icon = tray_icon or QSystemTrayIcon()
        self._owns_tray_icon = tray_icon is None
        application = QApplication.instance()
        if isinstance(application, QApplication):
            self._tray_icon.setIcon(application.windowIcon())
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()

    def show(self, title: str, message: str) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self._tray_icon.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            10_000,
        )
        return True

    def close(self) -> None:
        """Release the process-lifetime tray icon."""
        if self._owns_tray_icon:
            self._tray_icon.hide()


class QtReminderAdapter(QObject):
    """Poll every minute while keeping calculations in the application service."""

    due_count_changed = Signal(int)
    alert_summary_ready = Signal(str)
    digest_ready = Signal(object)
    failure = Signal(str)

    def __init__(
        self,
        service: ReminderService,
        interval_ms: int = 60_000,
        *,
        notification_sink: NotificationSink | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._now = now or (lambda: datetime.now(UTC))
        self._notification_sink = notification_sink or QtSystemTrayNotificationSink()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)
        self._last_digest_hour: datetime | None = None
        self._pending_digest: HourlyDigest | None = None
        self._displayed_digest: HourlyDigest | None = None
        self._digest_snoozed_until: datetime | None = None

    def start(self) -> None:
        self.poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        close = getattr(self._notification_sink, "close", None)
        if callable(close):
            close()

    def poll(self) -> None:
        """Perform one deterministic poll; useful directly in headless tests."""
        try:
            now = self._now()
            due = self._service.due()
            self.due_count_changed.emit(len(due))
            if due:
                summary = self._privacy_safe_summary(len(due))
                self.alert_summary_ready.emit(summary)
                self._notification_sink.show("ICU Patient Tracker", summary)
                self._service.mark_shown(reminder.id for reminder in due)
            self._poll_digest(now)
        except Exception as error:  # Qt callbacks cannot return errors to their caller.
            self.failure.emit(str(error))

    def snooze_digest(self) -> None:
        """Hide the current digest for the standard five-minute interval."""
        if self._displayed_digest is not None:
            self._pending_digest = self._displayed_digest
            self._digest_snoozed_until = self._now() + timedelta(minutes=5)

    def _poll_digest(self, now: datetime) -> None:
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self._last_digest_hour is None and now.minute != 0:
            self._last_digest_hour = hour
            return
        if self._last_digest_hour != hour:
            self._last_digest_hour = hour
            digest = self._service.hourly_digest()
            self._pending_digest = digest if digest.has_content else None
            self._displayed_digest = None
            self._digest_snoozed_until = None
        if self._pending_digest is None:
            return
        if self._digest_snoozed_until is not None and now < self._digest_snoozed_until:
            return
        self._displayed_digest = self._pending_digest
        self.digest_ready.emit(self._displayed_digest)
        self._pending_digest = None
        self._digest_snoozed_until = None

    @staticmethod
    def _privacy_safe_summary(due_count: int) -> str:
        visible_count = min(due_count, 3)
        lines = ["A scheduled reminder is due." for _ in range(visible_count)]
        if due_count > visible_count:
            lines.append(f"+{due_count - visible_count} more due reminder(s)")
        lines.append("Open the application to view details.")
        return "\n".join(lines)
