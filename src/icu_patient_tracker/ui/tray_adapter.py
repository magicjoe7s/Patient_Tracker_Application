"""Resident system-tray controls for the desktop application shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class DesktopTrayAdapter(QObject):
    """Expose window, board, pin, and shutdown controls through one tray icon."""

    def __init__(
        self,
        tray_icon: QSystemTrayIcon,
        *,
        is_window_visible: Callable[[], bool],
        is_window_pinned: Callable[[], bool],
        toggle_window: Callable[[], None],
        show_task_board: Callable[[], None],
        set_window_pinned: Callable[[bool], None],
        exit_application: Callable[[], None],
    ) -> None:
        super().__init__()
        self._tray_icon = tray_icon
        self._is_window_visible = is_window_visible
        self._is_window_pinned = is_window_pinned
        self._toggle_window = toggle_window
        self._menu = QMenu()
        self.show_hide_action = QAction("Show ICU Patient Tracker", self)
        self.task_board_action = QAction("Open Task Board", self)
        self.pin_action = QAction("Always on Top", self)
        self.pin_action.setCheckable(True)
        self.exit_action = QAction("Exit", self)
        self._menu.addAction(self.show_hide_action)
        self._menu.addAction(self.task_board_action)
        self._menu.addAction(self.pin_action)
        self._menu.addSeparator()
        self._menu.addAction(self.exit_action)
        self.show_hide_action.triggered.connect(toggle_window)
        self.task_board_action.triggered.connect(show_task_board)
        self.pin_action.toggled.connect(set_window_pinned)
        self.exit_action.triggered.connect(exit_application)
        self._menu.aboutToShow.connect(self.refresh)
        self._tray_icon.activated.connect(self._activate)
        self._tray_icon.setContextMenu(self._menu)
        self._tray_icon.setToolTip("ICU Patient Tracker")
        self.refresh()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()

    @property
    def is_available(self) -> bool:
        """Report whether the operating system exposes a usable tray area."""
        return QSystemTrayIcon.isSystemTrayAvailable()

    def refresh(self) -> None:
        """Synchronize action labels and checks with current window state."""
        visible = self._is_window_visible()
        label = "Hide ICU Patient Tracker" if visible else "Show ICU Patient Tracker"
        self.show_hide_action.setText(label)
        self.pin_action.blockSignals(True)
        self.pin_action.setChecked(self._is_window_pinned())
        self.pin_action.blockSignals(False)

    def close(self) -> None:
        """Remove the resident tray icon during a real application exit."""
        self._tray_icon.hide()

    def _activate(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_window()
