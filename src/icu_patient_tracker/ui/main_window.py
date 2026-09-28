"""Top-level application shell for the Phase VI clinical workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.dialogs.analytics_dialog import AnalyticsDialog
from icu_patient_tracker.dialogs.command_palette_dialog import (
    CommandPaletteDialog,
    GeneratedHelpDialog,
)
from icu_patient_tracker.dialogs.diagnostic_result_dialog import DiagnosticResultDialog
from icu_patient_tracker.dialogs.diagnostic_text_dialog import DiagnosticTextDialog
from icu_patient_tracker.dialogs.patient_popup import PatientPopup
from icu_patient_tracker.dialogs.patient_search_dialog import PatientSearchDialog
from icu_patient_tracker.dialogs.pending_diagnostics_dialog import PendingDiagnosticsDialog
from icu_patient_tracker.dialogs.reminder_digest_dialog import ReminderDigestDialog
from icu_patient_tracker.dialogs.settings_dialog import SettingsDialog
from icu_patient_tracker.dialogs.task_board_dialog import TaskBoardDialog
from icu_patient_tracker.domain.enums import AdmissionStatus, TaskCategory
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.services.exceptions import ApplicationServiceError
from icu_patient_tracker.services.recovery_service import RecoverySnapshot
from icu_patient_tracker.services.reminder_service import HourlyDigest
from icu_patient_tracker.services.task_service import TaskBoardRow
from icu_patient_tracker.ui.action_registry import (
    DEFAULT_ACTIONS,
    ActionRegistry,
    CommandParseError,
)
from icu_patient_tracker.ui.autosave_adapter import QtAutosaveAdapter
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.event_adapter import QtEventAdapter
from icu_patient_tracker.ui.recovery_adapter import QtRecoveryAdapter
from icu_patient_tracker.ui.reminder_adapter import QtReminderAdapter
from icu_patient_tracker.ui.theme_manager import ThemeManager
from icu_patient_tracker.widgets.day_workspace import DayWorkspace
from icu_patient_tracker.widgets.patient_panel import PatientPanel


class MainWindow(QMainWindow):
    """Compose injected presentation components without owning clinical logic."""

    exit_requested = Signal()

    def __init__(
        self,
        controller: PresentationController,
        events: QtEventAdapter,
        autosave: QtAutosaveAdapter,
        reminders: QtReminderAdapter,
        recovery: QtRecoveryAdapter,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._events = events
        self._autosave = autosave
        self._reminders = reminders
        self._recovery = recovery
        self._theme_manager = theme_manager
        self._registry = ActionRegistry(DEFAULT_ACTIONS)
        self._action_handlers = self._create_action_handlers()
        self._digest_dialog: ReminderDigestDialog | None = None
        self._task_board_dialog: TaskBoardDialog | None = None
        self._pending_diagnostics_dialog: PendingDiagnosticsDialog | None = None
        self._diagnostic_result_dialog: DiagnosticResultDialog | None = None
        self._diagnostic_result_from_task_board = False
        self._diagnostic_text_dialog: DiagnosticTextDialog | None = None
        self._patient_popup: PatientPopup | None = None
        self._patient_search_dialog: PatientSearchDialog | None = None
        self._help_dialog: GeneratedHelpDialog | None = None
        self._analytics_dialog: AnalyticsDialog | None = None
        self._legacy_menu: QMenu | None = None
        self._main_pinned = False
        self._close_to_tray = False
        self._exit_in_progress = False
        self._responsive_handoff_armed = True
        self._responsive_handoff_scheduled = False
        self._last_sidebar_width = 190
        self.setObjectName("mainWindow")
        self.setWindowTitle("ICU Patient Tracker")
        self.setMinimumSize(760, 520)
        self.resize(1270, 780)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self.patient_panel = PatientPanel(controller)
        self.workspace = DayWorkspace(controller)
        self.patient_panel.new_day_requested.connect(self.workspace.prompt_create_day)
        self.patient_panel.task_board_requested.connect(self._show_task_board)
        self.patient_panel.popup_requested.connect(self._toggle_patient_popup)
        self.patient_panel.backup_requested.connect(self._create_backup)
        self.patient_panel.collapse_requested.connect(self._toggle_sidebar)
        self.patient_panel.menu_requested.connect(self._show_legacy_menu)
        self.workspace.patient_summary.task_board_requested.connect(self._show_task_board)
        self.workspace.patient_summary.save_now_requested.connect(
            lambda: self._invoke_action("save")
        )
        self.workspace.charting.diagnostics_popup_requested.connect(
            self._show_diagnostic_text_editor
        )
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("centralWorkspace")
        self._splitter.addWidget(self.patient_panel)
        self.sidebar_toggle_rail = QWidget()
        self.sidebar_toggle_rail.setObjectName("sidebarToggleRail")
        self.sidebar_toggle_rail.setFixedWidth(18)
        toggle_layout = QVBoxLayout(self.sidebar_toggle_rail)
        toggle_layout.setContentsMargins(2, 0, 2, 0)
        toggle_layout.addStretch(1)
        self.sidebar_toggle_button = QPushButton("<")
        toggle_layout.addWidget(self.sidebar_toggle_button)
        toggle_layout.addStretch(1)
        self._splitter.addWidget(self.sidebar_toggle_rail)
        self._splitter.addWidget(self.workspace)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setStretchFactor(2, 1)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([190, 18, 1062])
        self.sidebar_toggle_button.setObjectName("sidebarToggle")
        self.sidebar_toggle_button.setAccessibleName("Collapse patient and task sidebar")
        self.sidebar_toggle_button.setToolTip("Collapse patient and task sidebar")
        self.sidebar_toggle_button.setStyleSheet(
            "QPushButton { border: 1px solid palette(mid); border-radius: 7px; "
            "min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px; "
            "padding: 0; font-size: 9px; font-weight: bold; background: palette(base); }"
            "QPushButton:hover { background: palette(alternate-base); }"
        )
        self.sidebar_toggle_button.setFixedSize(14, 14)
        self.sidebar_toggle_button.clicked.connect(self._toggle_sidebar)
        self.setCentralWidget(self._splitter)
        self._actions = self._create_actions()
        self._create_toolbar()
        self._create_menu_bar()
        self._save_status = QLabel("Saved")
        self._save_status.setAccessibleName("Save status")
        self.statusBar().addPermanentWidget(self._save_status)
        self._reminder_status = QLabel("No due reminders")
        self._reminder_status.setAccessibleName("Reminder status")
        self.statusBar().addPermanentWidget(self._reminder_status)
        self.statusBar().showMessage("Ready")
        self._connect_updates()
        self._restore_presentation_state()
        self._toolbar.hide()
        self.menuBar().hide()
        self._recovery.start()
        self._autosave.start()
        self._reminders.start()
        QTimer.singleShot(0, self._offer_recovery)

    @property
    def actions_by_name(self) -> dict[str, QAction]:
        """Return registered actions for tests and reusable command surfaces."""
        return dict(self._actions)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Flush pending editors and refuse shutdown when data cannot be saved."""
        if self._close_to_tray and not self._exit_in_progress:
            event.ignore()
            self.hide_to_tray()
            return
        if not self._controller.shutdown():
            QMessageBox.critical(
                self,
                "Unable to close safely",
                "Pending changes could not be saved. The application remains open so the data "
                "can be reviewed or saved again.",
            )
            event.ignore()
            return
        if self._patient_popup is not None:
            self._patient_popup.hide()
        if self._analytics_dialog is not None:
            self._analytics_dialog.hide()
        self._save_presentation_state()
        self._autosave.stop()
        self._reminders.stop()
        self._recovery.stop()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Hide the resident shell on Escape without ending the application."""
        if event.key() == Qt.Key.Key_Escape and self._close_to_tray:
            self.hide_to_tray()
            event.accept()
            return
        super().keyPressEvent(event)

    @property
    def is_main_pinned(self) -> bool:
        """Return the main window's always-on-top state."""
        return self._main_pinned

    def enable_tray_residency(self) -> None:
        """Make ordinary close and Escape actions hide the resident application."""
        self._close_to_tray = True

    def close_for_exit(self) -> bool:
        """Perform the real validated close requested by the application lifecycle."""
        self._exit_in_progress = True
        closed = self.close()
        if not closed:
            self._exit_in_progress = False
        return closed

    def is_shell_visible(self) -> bool:
        """Report whether any primary workflow window is currently visible."""
        return self.isVisible() or any(
            dialog is not None and dialog.isVisible()
            for dialog in (
                self._patient_popup,
                self._task_board_dialog,
                self._diagnostic_result_dialog,
            )
        )

    def activate_main_window(self) -> None:
        """Restore and focus the main window after tray, hotkey, or launch activation."""
        if self._patient_popup is not None:
            self._patient_popup.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self) -> None:
        """Commit active editors and hide workflow windows without ending the process."""
        if not self._close_to_tray or not self._controller.flush_pending():
            return
        self.hide()
        if self._patient_popup is not None:
            self._patient_popup.hide()
        if self._task_board_dialog is not None:
            self._task_board_dialog.hide()
        if self._diagnostic_result_dialog is not None:
            self._diagnostic_result_dialog.hide()

    def toggle_application_visibility(self) -> None:
        """Toggle the resident application between hidden and active states."""
        if self.is_shell_visible():
            self.hide_to_tray()
        else:
            self.activate_main_window()

    def toggle_task_board(self) -> None:
        """Toggle the Task Board independently for the global shortcut."""
        if self._task_board_dialog is not None and self._task_board_dialog.isVisible():
            self._task_board_dialog.hide()
        else:
            self._show_task_board()

    def show_diagnostic_result_capture(self) -> None:
        """Open result capture for the selected patient/day from the global hotkey."""
        if not self._controller.flush_pending():
            return
        patient_id = self._controller.context.patient_id
        day_id = self._controller.context.hospital_day_id
        if patient_id is None or day_id is None:
            self.statusBar().showMessage("Select a patient and hospital day first.", 5000)
            self.activate_main_window()
            return
        self._show_diagnostic_result(patient_id, day_id)

    def set_main_pin(self, pinned: bool) -> None:
        """Apply an explicit always-on-top state from the tray menu."""
        self._set_main_pin(pinned)

    def _create_actions(self) -> dict[str, QAction]:
        actions: dict[str, QAction] = {}
        for definition in self._registry.definitions:
            action = QAction(definition.label, self)
            action.setObjectName(f"action_{definition.name}")
            action.setStatusTip(definition.description)
            action.setShortcuts([QKeySequence(value) for value in definition.shortcuts])
            action.triggered.connect(
                lambda _checked=False, name=definition.name: self._invoke_action(name)
            )
            self.addAction(action)
            actions[definition.name] = action
        return actions

    def _create_toolbar(self) -> None:
        self._toolbar = QToolBar("Main", self)
        self._toolbar.setObjectName("mainToolbar")
        self._toolbar.setMovable(True)
        for definition in self._registry.definitions:
            if definition.toolbar:
                self._toolbar.addAction(self._actions[definition.name])
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)
        self._toolbar.hide()

    def _create_menu_bar(self) -> None:
        menus = {
            name: self.menuBar().addMenu(f"&{name}")
            for name in ("File", "Navigate", "View", "Tools", "Help")
        }
        for definition in self._registry.definitions:
            if definition.menu is not None:
                menus[definition.menu].addAction(self._actions[definition.name])
        menus["View"].addAction(self._toolbar.toggleViewAction())
        self.menuBar().hide()

    def _create_action_handlers(self) -> dict[str, Callable[[str | None], object]]:
        return {
            "new_patient": lambda _argument: self.patient_panel.prompt_create(),
            "new_day": lambda _argument: self.workspace.prompt_create_day(),
            "save": lambda _argument: self._controller.flush_pending(),
            "create_backup": lambda _argument: self._create_backup(),
            "restore_backup": lambda _argument: self._restore_backup(),
            "exit": lambda _argument: self.exit_requested.emit(),
            "find": lambda _argument: self._show_patient_search(),
            "previous_patient": lambda _argument: self._select_relative_patient(-1),
            "next_patient": lambda _argument: self._select_relative_patient(1),
            "previous_day": lambda _argument: self.workspace.move_day(-1),
            "next_day": lambda _argument: self.workspace.move_day(1),
            "rename_patient": lambda _argument: self.patient_panel.prompt_rename(),
            "new_todo": lambda _argument: self.workspace.tasks.prompt_add(TaskCategory.CLINICAL),
            "new_diagnostic": lambda _argument: self.workspace.tasks.prompt_add(
                TaskCategory.DIAGNOSTIC
            ),
            "patient_popup": lambda _argument: self._toggle_patient_popup(),
            "sandbox_popup": lambda _argument: self._show_patient_popup("sandbox"),
            "toggle_soap": lambda _argument: self._toggle_soap_workspace(),
            "task_board": lambda _argument: self._show_task_board(),
            "pending_diagnostics": lambda _argument: self._show_pending_diagnostics(),
            "hide_completed": lambda _argument: self._set_completed_visibility(False),
            "show_completed": lambda _argument: self._set_completed_visibility(True),
            "toggle_pin": lambda _argument: self._toggle_main_pin(),
            "toggle_sidebar": lambda _argument: self._toggle_sidebar(),
            "resize_small": lambda _argument: self.resize(800, 550),
            "resize_medium": lambda _argument: self.resize(1040, 700),
            "resize_large": lambda _argument: self.resize(1270, 780),
            "resize_fit": lambda _argument: self._fit_monitor(),
            "copy_soap": lambda _argument: self.workspace.soap.copy_to_clipboard(),
            "analytics": lambda _argument: self._show_analytics(),
            "settings": lambda _argument: self._show_settings(),
            "command_palette": lambda _argument: self._show_command_palette(),
            "help": lambda _argument: self._show_generated_help(),
            "select_patient": lambda argument: self._select_patient_command(argument or ""),
            "select_day": lambda argument: self._select_day_command(argument or ""),
            "readmit": lambda argument: self._readmit_command(argument),
            "set_status": lambda argument: self._set_status_command(argument or ""),
            "focus": lambda argument: self._focus_command(argument or ""),
            "focus_problem": lambda _argument: self._focus_command("problem"),
            "focus_exam": lambda _argument: self._focus_command("exam"),
            "focus_treatment": lambda _argument: self._focus_command("treatment"),
        }

    def _create_backup(self) -> None:
        path = self._controller.create_backup()
        if path is not None:
            QMessageBox.information(
                self,
                "Backup created",
                f"A verified backup was created at:\n\n{path}",
            )

    def _restore_backup(self) -> None:
        config = self._controller.settings()
        initial = str(config.backup_directory) if config is not None else ""
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Select ICU Patient Tracker Backup",
            initial,
            "SQLite backups (*.sqlite3);;All files (*)",
        )
        if not selected:
            return
        descriptor = self._controller.inspect_backup(Path(selected))
        if descriptor is None:
            return
        answer = QMessageBox.warning(
            self,
            "Confirm database restore",
            (
                "Restoring replaces the current database with the reviewed backup. A verified "
                "pre-restore safety backup will be created first.\n\n"
                f"File: {descriptor.path.name}\n"
                f"Size: {descriptor.size_bytes:,} bytes\n"
                f"SHA-256: {descriptor.sha256[:16]}…\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        safety_backup = self._controller.restore_backup(descriptor)
        if safety_backup is None:
            return
        self.patient_panel.refresh()
        self.workspace.refresh()
        QMessageBox.information(
            self,
            "Restore complete",
            (
                "The selected backup was restored and reopened successfully.\n\n"
                f"Pre-restore safety backup:\n{safety_backup}"
            ),
        )

    def _invoke_action(self, name: str, argument: str | None = None) -> object:
        return self._action_handlers[name](argument)

    def execute_command(self, raw: str) -> bool:
        """Parse and dispatch one typed command from any presentation surface."""
        try:
            parsed = self._registry.parse(raw)
        except CommandParseError as error:
            self._controller.error_raised.emit("Command Palette", str(error))
            return False
        self._invoke_action(parsed.action_name, parsed.argument)
        return True

    def _show_command_palette(self) -> None:
        dialog = CommandPaletteDialog(self._registry, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.execute_command(dialog.command_text())

    def _show_generated_help(self) -> None:
        if self._help_dialog is None:
            self._help_dialog = GeneratedHelpDialog(self._registry, self)
            self._help_dialog.command_palette_requested.connect(self._show_command_palette)
        self._help_dialog.text.setPlainText(self._registry.help_text())
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _show_analytics(self) -> None:
        if self._analytics_dialog is None:
            self._analytics_dialog = AnalyticsDialog(self._controller, self)
        self._analytics_dialog.refresh()
        self._analytics_dialog.show()
        self._analytics_dialog.raise_()
        self._analytics_dialog.activateWindow()

    def _select_relative_patient(self, offset: int) -> bool:
        patients = self._controller.patients()
        if not patients:
            self._controller.error_raised.emit(
                "Patient navigation", "No active patients are available."
            )
            return False
        current_id = self._controller.context.patient_id
        current = next(
            (index for index, patient in enumerate(patients) if patient.id == current_id),
            None,
        )
        destination = 0 if current is None else (current + offset) % len(patients)
        return self._controller.select_patient(patients[destination].id)

    def _select_patient_command(self, query: str) -> bool:
        matches = self._controller.patients(query)
        if not matches:
            self._controller.error_raised.emit(
                "Command Palette", f"No active patient matches: {query}"
            )
            return False
        return self._controller.select_patient(matches[0].id)

    def _select_day_command(self, query: str) -> bool:
        patient_id = self._controller.context.patient_id
        if patient_id is None:
            self._controller.error_raised.emit("Command Palette", "Select a patient first.")
            return False
        normalized = query.strip().casefold()
        days = self._controller.services.days.list(patient_id)
        selected = next(
            (
                day
                for day in days
                if normalized == day.calendar_date.isoformat().casefold()
                or (day.label is not None and normalized in day.label.casefold())
                or normalized == f"icu {day.day_number}"
            ),
            None,
        )
        if selected is None:
            self._controller.error_raised.emit("Command Palette", f"No matching day found: {query}")
            return False
        return self._controller.select_day(selected.id)

    def _readmit_command(self, query: str | None) -> bool:
        value = query or ""
        if not value:
            value, accepted = QInputDialog.getText(self, "Readmit To ICU", "Home/IMC patient name:")
            if not accepted:
                return False
        candidates = (
            *self._controller.patients(value, status=AdmissionStatus.DISCHARGED),
            *self._controller.patients(value, status=AdmissionStatus.TRANSFERRED),
        )
        if not candidates:
            self._controller.error_raised.emit(
                "Command Palette", f"No Home or IMC patient matches: {value}"
            )
            return False
        patient = min(
            candidates,
            key=lambda item: (item.name.casefold() != value.casefold(), item.name.casefold()),
        )
        if self._controller.readmit_patient(patient.id) is None:
            return False
        return self._controller.select_patient(patient.id)

    def _set_status_command(self, value: str) -> bool:
        aliases = {
            "active": AdmissionStatus.ADMITTED,
            "activate": AdmissionStatus.ADMITTED,
            "home": AdmissionStatus.DISCHARGED,
            "imc": AdmissionStatus.TRANSFERRED,
            "archive": AdmissionStatus.ARCHIVED,
            "archived": AdmissionStatus.ARCHIVED,
            "death": AdmissionStatus.DECEASED,
            "dead": AdmissionStatus.DECEASED,
            "deceased": AdmissionStatus.DECEASED,
            "euthanized": AdmissionStatus.DECEASED,
            "euthanasia": AdmissionStatus.DECEASED,
        }
        status = aliases.get(value.strip().casefold())
        patient_id = self._controller.context.patient_id
        if status is None:
            self._controller.error_raised.emit(
                "Command Palette", "Use status active, home, imc, archive, or death."
            )
            return False
        if patient_id is None:
            self._controller.error_raised.emit("Command Palette", "Select a patient first.")
            return False
        if status in {AdmissionStatus.ARCHIVED, AdmissionStatus.DECEASED}:
            answer = QMessageBox.question(
                self,
                "Confirm disposition",
                f"Set the selected patient to {status.value}?",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return False
        return self._controller.change_patient_status(patient_id, status) is not None

    def _focus_command(self, target: str) -> bool:
        normalized = target.strip().casefold()
        if normalized == "search":
            self.patient_panel.search.setFocus()
            return True
        if normalized == "tree":
            self.patient_panel.list_view.setFocus()
            return True
        if normalized == "problem":
            self.workspace.tabs.setCurrentWidget(self.workspace.problems)
            self.workspace.problems.list_view.setFocus()
            return True
        task_categories = {
            "todo": TaskCategory.CLINICAL,
            "reminders": TaskCategory.CLINICAL,
            "pocus": TaskCategory.POCUS,
            "pending": TaskCategory.DIAGNOSTIC,
        }
        if normalized in task_categories:
            self.workspace.tabs.setCurrentWidget(self.workspace.tasks)
            category = task_categories[normalized]
            self.workspace.tasks.select_category(category)
            self.workspace.tasks.list_view.setFocus()
            return True
        if normalized in {"devices", "lines"}:
            self.workspace.tabs.setCurrentWidget(self.workspace.devices_page)
            self.workspace.instrumentation.editor.setFocus()
            return True
        if normalized == "soap":
            self.workspace.tabs.setCurrentWidget(self.workspace.soap)
            self.workspace.soap.markdown.setFocus()
            return True
        charting_targets = {
            "treatment": self.workspace.charting.treatment,
            "exam": self.workspace.charting.examination,
            "pe": self.workspace.charting.examination,
            "physical": self.workspace.charting.examination,
        }
        editor = charting_targets.get(normalized)
        if editor is not None:
            self.workspace.tabs.setCurrentWidget(self.workspace.charting)
            editor.setFocus()
            return True
        self._controller.error_raised.emit("Command Palette", f"Unknown focus target: {target}")
        return False

    def _toggle_soap_workspace(self) -> None:
        target = (
            self.workspace.charting
            if self.workspace.tabs.currentWidget() is self.workspace.soap
            else self.workspace.soap
        )
        self.workspace.tabs.setCurrentWidget(target)
        if target is self.workspace.soap:
            self.workspace.soap.markdown.setFocus()

    def _set_completed_visibility(self, visible: bool) -> None:
        hidden = not visible
        self.workspace.tasks.set_all_hide_completed(hidden)
        self.patient_panel.sidebar_tasks.set_all_hide_completed(hidden)
        if self._task_board_dialog is not None:
            for pane in self._task_board_dialog.panes.values():
                pane.hide_completed.setChecked(hidden)
        if self._pending_diagnostics_dialog is not None:
            self._pending_diagnostics_dialog.hide_completed.setChecked(hidden)

    def _toggle_main_pin(self) -> None:
        self._set_main_pin(not self._main_pinned)

    def _set_main_pin(self, pinned: bool) -> None:
        was_visible = self.isVisible()
        self._main_pinned = pinned
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        if was_visible:
            self.show()

    def _toggle_sidebar(self) -> None:
        visible = not self.patient_panel.isHidden()
        if visible:
            sizes = self._splitter.sizes()
            if sizes and sizes[0] > 0:
                self._last_sidebar_width = sizes[0]
            self.patient_panel.hide()
        else:
            self.patient_panel.show()
            available = max(self._splitter.width() - self.sidebar_toggle_rail.width(), 1)
            sidebar_width = min(self._last_sidebar_width, max(1, available - 1))
            self._splitter.setSizes(
                [sidebar_width, self.sidebar_toggle_rail.width(), available - sidebar_width]
            )
        self._update_sidebar_toggle()

    def _position_sidebar_toggle(self) -> None:
        """Compatibility seam; the layout-owned rail now fixes the button position."""
        self.sidebar_toggle_rail.setVisible(True)

    def _update_sidebar_toggle(self) -> None:
        expanded = not self.patient_panel.isHidden()
        label = "<" if expanded else ">"
        action = "Collapse" if expanded else "Open"
        self.sidebar_toggle_button.setText(label)
        self.sidebar_toggle_button.setAccessibleName(f"{action} patient and task sidebar")
        self.sidebar_toggle_button.setToolTip(f"{action} patient and task sidebar")
        self.patient_panel.collapse_button.setText(label)

    def _show_legacy_menu(self) -> None:
        if self._legacy_menu is None:
            self._legacy_menu = QMenu("Tracker Menu", self)
            previous_menu: str | None = None
            for definition in self._registry.definitions:
                if definition.menu is None:
                    continue
                if previous_menu is not None and definition.menu != previous_menu:
                    self._legacy_menu.addSeparator()
                self._legacy_menu.addAction(self._actions[definition.name])
                previous_menu = definition.menu
            self._legacy_menu.addSeparator()
            self.patient_panel.patient_menu.setTitle("Selected Patient")
            self._legacy_menu.addMenu(self.patient_panel.patient_menu)
            self._legacy_menu.addAction(self._toolbar.toggleViewAction())
        button = self.patient_panel.menu_button
        self._legacy_menu.popup(button.mapToGlobal(button.rect().topLeft()))

    def _fit_monitor(self) -> None:
        geometry = self.screen().availableGeometry()
        width = max(self.minimumWidth(), int(geometry.width() * 0.9))
        height = max(self.minimumHeight(), int(geometry.height() * 0.9))
        self.resize(width, height)
        self.move(
            geometry.x() + (geometry.width() - width) // 2,
            geometry.y() + (geometry.height() - height) // 2,
        )

    def _connect_updates(self) -> None:
        self._controller.save_status_changed.connect(self._handle_save_status)
        self._controller.operation_status.connect(
            lambda message: self.statusBar().showMessage(message, 4000)
        )
        self._controller.error_raised.connect(self._show_error)
        self._controller.context_changed.connect(lambda _context: self._refresh_context_dialogs())
        self.workspace.soap.popup_requested.connect(self._show_patient_popup)
        self.workspace.sandbox.popup_requested.connect(self._show_patient_popup)
        self._events.patient_changed.connect(self._refresh_patient_views)
        self._events.day_changed.connect(self._refresh_day_views)
        self._events.problem_changed.connect(self._refresh_problem_views)
        self._events.task_changed.connect(self._refresh_task_views)
        self._events.instrumentation_changed.connect(self._refresh_instrumentation_views)
        self._events.soap_changed.connect(self._refresh_soap_views)
        self._events.settings_changed.connect(lambda _op: self._refresh_settings())
        self._events.persistence_changed.connect(self._save_status.setText)
        self._events.any_changed.connect(lambda _event: self._refresh_analytics())
        self._autosave.failure.connect(lambda message: self._show_error("Autosave failed", message))
        self._reminders.due_count_changed.connect(
            lambda count: self._reminder_status.setText(
                "No due reminders" if count == 0 else f"{count} due reminder(s)"
            )
        )
        self._reminders.alert_summary_ready.connect(
            lambda summary: self.statusBar().showMessage(summary.replace("\n", " "), 10_000)
        )
        self._reminders.digest_ready.connect(self._show_reminder_digest)
        self._reminders.failure.connect(
            lambda message: self.statusBar().showMessage(f"Reminder check failed: {message}", 8000)
        )
        self._recovery.failure.connect(
            lambda message: self._show_error("Recovery snapshot failed", message)
        )

    def _handle_save_status(self, status: str) -> None:
        self._save_status.setText(status)
        if status == "Saved":
            QTimer.singleShot(0, self._refresh_structured_soap_fields)

    def _offer_recovery(self) -> None:
        snapshot = self._controller.recovery_snapshot()
        if snapshot is None:
            return
        answer = QMessageBox.question(
            self,
            "Recover unsaved draft",
            (
                f"Unsaved editor text from {snapshot.created_at:%Y-%m-%d %H:%M} was found.\n\n"
                "Load it into the editors for review? It will remain unsaved until you choose "
                "Save. Choose No to discard the snapshot, or Cancel to keep it for later."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.No:
            self._controller.discard_recovery()
            return
        if answer is not QMessageBox.StandardButton.Yes:
            return
        if not self._select_recovery_context(snapshot):
            QMessageBox.warning(
                self,
                "Recovery context unavailable",
                "The patient or hospital day recorded by this draft no longer exists. The "
                "snapshot was retained for manual review.",
            )
            return
        current = self._recovery_values()
        conflicts = self._controller.recovery_conflicts(snapshot, current)
        if conflicts is None:
            return
        if conflicts:
            conflict_answer = QMessageBox.warning(
                self,
                "Saved record changed",
                (
                    "Saved data changed after this draft was created for: "
                    f"{', '.join(conflicts)}.\n\n"
                    "Load the draft into unsaved editors for comparison? Nothing will be "
                    "overwritten until you explicitly save."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if conflict_answer is not QMessageBox.StandardButton.Yes:
                return
        try:
            self._apply_recovery(snapshot)
        except (KeyError, ValueError):
            QMessageBox.warning(
                self,
                "Recovery draft invalid",
                "The recovery fields are incomplete or invalid. The snapshot was retained.",
            )
            return
        self._controller.context.save_status = "Recovered draft — review before saving"
        self._controller.save_status_changed.emit(self._controller.context.save_status)
        self.statusBar().showMessage("Recovered draft loaded; review and save explicitly", 10_000)

    def _select_recovery_context(self, snapshot: RecoverySnapshot) -> bool:
        try:
            patient = self._controller.services.patients.get(snapshot.patient_id)
        except ApplicationServiceError:
            return False
        if snapshot.hospital_day_id is not None and all(
            day.id != snapshot.hospital_day_id for day in patient.hospital_days
        ):
            return False
        if not self._controller.select_patient(snapshot.patient_id):
            return False
        return snapshot.hospital_day_id is None or self._controller.select_day(
            snapshot.hospital_day_id
        )

    def _recovery_values(self) -> dict[str, dict[str, str]]:
        return {
            "patient-summary": self.workspace.patient_summary.recovery_values(),
            "problem-list": self.workspace.patient_summary.problem_recovery_values(),
            "charting": self.workspace.charting.recovery_values(),
            "instrumentation": self.workspace.instrumentation.recovery_values(),
            "soap": self.workspace.soap.recovery_values(),
            "sandbox": self.workspace.sandbox.recovery_values(),
        }

    def _apply_recovery(self, snapshot: RecoverySnapshot) -> None:
        for entry in snapshot.entries:
            if entry.key == "patient-summary":
                self.workspace.patient_summary.apply_recovery(entry.values)
            elif entry.key == "problem-list":
                self.workspace.patient_summary.apply_problem_recovery(entry.values)
            elif entry.key == "charting":
                self.workspace.charting.apply_recovery(entry.values)
            elif entry.key == "instrumentation":
                self.workspace.instrumentation.apply_recovery(entry.values)
            elif entry.key == "soap":
                self.workspace.soap.apply_recovery(entry.values)
            elif entry.key == "sandbox":
                self.workspace.sandbox.apply_recovery(entry.values)

    def _show_reminder_digest(self, digest: object) -> None:
        if not isinstance(digest, HourlyDigest):
            return
        if self._digest_dialog is not None:
            self._digest_dialog.close()
        dialog = ReminderDigestDialog(digest, self)
        self._digest_dialog = dialog
        dialog.snoozed.connect(self._reminders.snooze_digest)
        dialog.task_completed.connect(self._complete_digest_task)
        dialog.destroyed.connect(lambda _object=None: self._clear_digest_dialog(dialog))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _complete_digest_task(self, patient_id: object, task_id: object) -> None:
        if isinstance(patient_id, UUID) and isinstance(task_id, UUID):
            self._controller.complete_digest_task(patient_id, task_id)

    def _clear_digest_dialog(self, dialog: ReminderDigestDialog) -> None:
        if self._digest_dialog is dialog:
            self._digest_dialog = None

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self._controller, self)
        dialog.applied.connect(self._apply_theme)
        dialog.exec()

    def _show_task_board(self) -> None:
        if self._task_board_dialog is None:
            self._task_board_dialog = TaskBoardDialog(self._controller, self)
            self._task_board_dialog.navigated.connect(self._return_from_task_board)
            self._task_board_dialog.diagnostic_result_requested.connect(
                self._show_diagnostic_result_for_board_row
            )
        self._task_board_dialog.refresh()
        self._task_board_dialog.show()
        self._task_board_dialog.raise_()
        self._task_board_dialog.activateWindow()

    def _show_patient_search(self) -> None:
        if self._patient_search_dialog is None:
            self._patient_search_dialog = PatientSearchDialog(self._controller, self)
        self._patient_search_dialog.show_search()

    def _show_pending_diagnostics(self) -> None:
        if self._pending_diagnostics_dialog is None:
            self._pending_diagnostics_dialog = PendingDiagnosticsDialog(self._controller, self)
            self._pending_diagnostics_dialog.result_requested.connect(
                self._show_diagnostic_result_for_task
            )
        self._pending_diagnostics_dialog.refresh()
        self._pending_diagnostics_dialog.show()
        self._pending_diagnostics_dialog.raise_()
        self._pending_diagnostics_dialog.activateWindow()

    def _show_diagnostic_result_for_task(self, task: Task) -> None:
        self._show_diagnostic_result(task.patient_id, task.hospital_day_id, task.id)

    def _show_diagnostic_result_for_board_row(self, row: TaskBoardRow) -> None:
        self._diagnostic_result_from_task_board = True
        if self._task_board_dialog is not None:
            self._task_board_dialog.showMinimized()
        self._show_diagnostic_result(row.patient_id, row.hospital_day_id, row.task.id)

    def _show_diagnostic_result(
        self, patient_id: object, day_id: object, task_id: object = None
    ) -> None:
        from uuid import UUID

        if not isinstance(patient_id, UUID) or not isinstance(day_id, UUID):
            return
        selected_task = task_id if isinstance(task_id, UUID) else None
        if self._diagnostic_result_dialog is None:
            # Keep result capture independent so minimizing the tracker exposes the EMR
            # without also hiding the always-on-top capture window.
            self._diagnostic_result_dialog = DiagnosticResultDialog(self._controller)
            self._diagnostic_result_dialog.closed.connect(
                self._return_from_diagnostic_result
            )
        self.showMinimized()
        self._diagnostic_result_dialog.show_for(patient_id, day_id, selected_task)

    def _return_from_diagnostic_result(self) -> None:
        if not self._diagnostic_result_from_task_board:
            return
        self._diagnostic_result_from_task_board = False
        if self._task_board_dialog is not None:
            self._task_board_dialog.refresh()
            self._task_board_dialog.showNormal()
            self._task_board_dialog.raise_()
            self._task_board_dialog.activateWindow()

    def _show_diagnostic_text_editor(self) -> None:
        patient = self._controller.selected_patient()
        day = self._controller.selected_day()
        if patient is None or day is None:
            return
        if self._diagnostic_text_dialog is None:
            self._diagnostic_text_dialog = DiagnosticTextDialog()
            self._diagnostic_text_dialog.saved.connect(self._save_diagnostic_text_editor)
            self._diagnostic_text_dialog.finished.connect(
                lambda _result: self._return_from_diagnostic_text_editor()
            )
        context = f"{patient.name} · ICU {day.day_number} · {day.calendar_date.isoformat()}"
        self.showMinimized()
        self._diagnostic_text_dialog.show_for(
            context, self.workspace.charting.diagnostics.toPlainText()
        )

    def _save_diagnostic_text_editor(self, value: str) -> None:
        self.workspace.charting.diagnostics.setPlainText(value)
        if self.workspace.charting.save() and self._diagnostic_text_dialog is not None:
            self._diagnostic_text_dialog.accept()

    def _return_from_diagnostic_text_editor(self) -> None:
        self.workspace.charting.refresh()
        self.workspace.soap.refresh(force=True)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_patient_popup(self) -> None:
        if self._patient_popup is not None and self._patient_popup.isVisible():
            self._patient_popup.return_to_main()
            return
        self._show_patient_popup("soap")

    def _show_patient_popup(self, mode: str = "soap") -> None:
        if not self._controller.flush_pending():
            return
        if self._patient_popup is None:
            self._patient_popup = PatientPopup(self._controller, self)
            self._patient_popup.returned_to_main.connect(self._return_from_patient_popup)
            self._patient_popup.save_requested.connect(self._save_from_patient_popup)
            self._patient_popup.new_patient_requested.connect(
                self._new_patient_from_patient_popup
            )
            self._patient_popup.find_patient_requested.connect(self._show_patient_search)
        self._patient_popup.show_for(mode)
        self.hide()

    def _save_from_patient_popup(self) -> None:
        if self._patient_popup is None:
            return
        if self._controller.flush_pending():
            self._patient_popup.status_label.setText("Saved")
        else:
            self._patient_popup.status_label.setText("Save failed")

    def _new_patient_from_patient_popup(self) -> None:
        self.patient_panel.prompt_create()
        self.hide()
        if self._patient_popup is not None:
            self._patient_popup.show()
            self._patient_popup.raise_()
            self._patient_popup.activateWindow()

    def _return_from_patient_popup(self) -> None:
        self._responsive_handoff_armed = False
        self.workspace.soap.refresh(force=True)
        self.workspace.sandbox.refresh(force=True)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _return_from_task_board(self) -> None:
        if self._task_board_dialog is not None:
            self._task_board_dialog.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _refresh_task_views(self, _task_id: str, _operation: str) -> None:
        self.workspace.tasks.refresh()
        self.patient_panel.sidebar_tasks.refresh()
        if self._task_board_dialog is not None:
            self._task_board_dialog.refresh()
        if self._pending_diagnostics_dialog is not None:
            self._pending_diagnostics_dialog.refresh()
        if (
            self._diagnostic_result_dialog is not None
            and self._diagnostic_result_dialog.isVisible()
        ):
            self._diagnostic_result_dialog.refresh()
        self.workspace.charting.refresh_diagnostic_results()

    def _refresh_problem_views(self, _problem_id: str, _operation: str) -> None:
        self.workspace.problems.refresh()
        self.workspace.patient_summary.refresh_running_problems(
            force=_operation == "soap_problem_list"
        )
        if _operation != "soap_problem_list":
            self._controller.refresh_selected_problem_list_in_soap()

    def _refresh_instrumentation_views(self, _device_id: str, _operation: str) -> None:
        self.workspace.instrumentation.refresh(force=_operation == "soap_instrumentation")
        self.workspace.charting.refresh_device_summary(
            force=_operation == "soap_instrumentation"
        )
        if _operation != "soap_instrumentation":
            self._controller.refresh_selected_instrumentation_in_soap()

    def _refresh_context_dialogs(self) -> None:
        if self._pending_diagnostics_dialog is not None:
            self._pending_diagnostics_dialog.refresh()

    def _refresh_day_views(self, _day_id: str, _operation: str) -> None:
        self.workspace.refresh_day_views()
        if self._patient_popup is not None:
            self._patient_popup.refresh(force=False)

    def _refresh_soap_views(self, _soap_id: str, _operation: str) -> None:
        canonical_refresh = (
            _operation == "markdown_refreshed" and not self._controller.has_pending_editor("soap")
        )
        self.workspace.soap.refresh(force=canonical_refresh)
        if self._patient_popup is not None:
            self._patient_popup.refresh(force=canonical_refresh)
        # SOAP saves may reverse-map code status and day acuity while the autosave
        # commit still owns the dirty flag. Refresh again after that commit unwinds.
        QTimer.singleShot(0, self._refresh_structured_soap_fields)

    def _refresh_structured_soap_fields(self) -> None:
        if self._controller.context.is_dirty:
            return
        self.workspace.patient_summary.refresh()
        self.workspace.charting.refresh()
        self.patient_panel.refresh()

    def _refresh_patient_views(self, _patient_id: str, _operation: str) -> None:
        self.patient_panel.refresh()
        self.workspace.refresh_patient_views()
        if _operation == "soap_patient_summary":
            self.workspace.patient_summary.refresh(force=True)

    def _refresh_analytics(self) -> None:
        if self._analytics_dialog is not None and self._analytics_dialog.isVisible():
            self._analytics_dialog.refresh()

    def _apply_theme(self) -> None:
        application = QApplication.instance()
        config = self._controller.settings()
        if isinstance(application, QApplication) and config is not None:
            self._theme_manager.apply(application, config.theme)

    def _refresh_settings(self) -> None:
        self._apply_theme()
        self.workspace.tasks.reload_hide_preferences()
        self.patient_panel.sidebar_tasks.reload_hide_preferences()
        if self._task_board_dialog is not None:
            for pane in self._task_board_dialog.panes.values():
                pane.reload_hide_preference()
        if self._pending_diagnostics_dialog is not None:
            self._pending_diagnostics_dialog.reload_hide_preference()

    def _show_error(self, title: str, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        QMessageBox.warning(self, title, message)

    def _restore_presentation_state(self) -> None:
        config = self._controller.settings()
        if config is None:
            return
        geometry = config.user_preferences.get("window_geometry")
        state = config.user_preferences.get("window_state")
        splitter = config.user_preferences.get("splitter_sizes")
        sidebar_visible = config.user_preferences.get("sidebar_visible")
        pinned = config.user_preferences.get("main_window_pinned")
        if isinstance(geometry, str):
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        if isinstance(state, str):
            self.restoreState(QByteArray.fromBase64(state.encode("ascii")))
        if isinstance(splitter, list) and all(isinstance(size, int) for size in splitter):
            # Migrate the former 330 px default without overriding widths that the
            # clinician deliberately resized.
            if splitter and 325 <= splitter[0] <= 335:
                splitter = [190, *splitter[1:]]
            if len(splitter) == 2:
                self._splitter.setSizes(
                    [splitter[0], self.sidebar_toggle_rail.width(), splitter[1]]
                )
            elif len(splitter) == 3:
                self._splitter.setSizes(
                    [splitter[0], self.sidebar_toggle_rail.width(), splitter[2]]
                )
            if splitter and splitter[0] > 0:
                self._last_sidebar_width = splitter[0]
        if sidebar_visible is False:
            self.patient_panel.hide()
        self._update_sidebar_toggle()
        if isinstance(pinned, bool):
            self._set_main_pin(pinned)

    def _save_presentation_state(self) -> None:
        config = self._controller.settings()
        if config is None:
            return
        preferences = dict(config.user_preferences)
        preferences.update(
            {
                "window_geometry": bytes(self.saveGeometry().toBase64().data()).decode("ascii"),
                "window_state": bytes(self.saveState().toBase64().data()).decode("ascii"),
                "splitter_sizes": self._splitter.sizes(),
                "sidebar_visible": not self.patient_panel.isHidden(),
                "main_window_pinned": self._main_pinned,
            }
        )
        self._controller.update_settings(user_preferences=preferences)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        size = event.size()
        if size.width() >= 820 and size.height() >= 600:
            self._responsive_handoff_armed = True
            return
        if (
            not self.isVisible()
            or not self._responsive_handoff_armed
            or self._responsive_handoff_scheduled
            or self._controller.context.hospital_day_id is None
        ):
            return
        self._responsive_handoff_scheduled = True

        def handoff() -> None:
            self._responsive_handoff_scheduled = False
            if self.isVisible() and self._responsive_handoff_armed:
                self._show_patient_popup("soap")

        QTimer.singleShot(0, handoff)
