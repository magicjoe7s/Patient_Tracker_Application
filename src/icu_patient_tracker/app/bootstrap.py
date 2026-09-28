"""Single composition root for infrastructure, services, adapters, and views."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.app.single_instance import SingleInstanceCoordinator
from icu_patient_tracker.persistence.autosave import AutosaveController
from icu_patient_tracker.persistence.backup import BackupManager
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.recovery import RecoveryStore
from icu_patient_tracker.resources.application_icon import load_application_icon
from icu_patient_tracker.services.analytics_service import AnalyticsService
from icu_patient_tracker.services.autosave_coordinator import AutosaveCoordinator
from icu_patient_tracker.services.backup_service import BackupService
from icu_patient_tracker.services.clinical_sync_service import ClinicalSyncService
from icu_patient_tracker.services.clipboard_service import ClipboardService
from icu_patient_tracker.services.common import UnitOfWorkFactory
from icu_patient_tracker.services.diagnostic_result_service import DiagnosticResultService
from icu_patient_tracker.services.events import InProcessEventDispatcher
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.instrumentation_service import InstrumentationService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.problem_service import ProblemService
from icu_patient_tracker.services.recovery_service import RecoveryService
from icu_patient_tracker.services.reminder_service import ReminderService
from icu_patient_tracker.services.sandbox_service import SandboxService
from icu_patient_tracker.services.search_service import SearchService
from icu_patient_tracker.services.settings_service import SettingsService
from icu_patient_tracker.services.soap_service import SOAPService
from icu_patient_tracker.services.task_service import TaskService
from icu_patient_tracker.ui.autosave_adapter import QtAutosaveAdapter
from icu_patient_tracker.ui.clipboard_adapter import QtClipboardAdapter
from icu_patient_tracker.ui.controller import PresentationController, ServiceBundle
from icu_patient_tracker.ui.event_adapter import QtEventAdapter
from icu_patient_tracker.ui.global_hotkeys import GlobalHotkeyManager
from icu_patient_tracker.ui.main_window import MainWindow
from icu_patient_tracker.ui.recovery_adapter import QtRecoveryAdapter
from icu_patient_tracker.ui.reminder_adapter import (
    QtReminderAdapter,
    QtSystemTrayNotificationSink,
)
from icu_patient_tracker.ui.sync_adapter import QtSyncAdapter
from icu_patient_tracker.ui.theme_manager import ThemeManager
from icu_patient_tracker.ui.tray_adapter import DesktopTrayAdapter
from icu_patient_tracker.utils.logging_config import initialize_logging, set_log_level


@dataclass(slots=True, weakref_slot=True)
class ApplicationRuntime:
    """Own every process-lifetime resource created by the composition root."""

    application: QApplication
    window: MainWindow
    database: DatabaseManager
    config: AppConfig
    logger: logging.Logger
    controller: PresentationController
    events: QtEventAdapter
    autosave: QtAutosaveAdapter
    reminders: QtReminderAdapter
    recovery: QtRecoveryAdapter
    tray: DesktopTrayAdapter | None = None
    global_hotkeys: GlobalHotkeyManager | None = None
    _is_shutdown: bool = False
    sync: QtSyncAdapter | None = None

    def shutdown(self) -> bool:
        """Close safely, then release adapters and persistence resources once."""
        if self._is_shutdown:
            return True
        self.logger.info("Application shutdown started")
        if not self.window.close_for_exit():
            self.logger.warning("Application shutdown cancelled because pending data was not saved")
            return False
        if self.sync is not None:
            self.sync.stop()
        if self.global_hotkeys is not None:
            self.global_hotkeys.stop()
        if self.tray is not None:
            self.tray.close()
        self.autosave.stop()
        self.reminders.stop()
        self.recovery.stop()
        self.events.close()
        self.database.dispose()
        self._is_shutdown = True
        self.logger.info("Application shutdown complete")
        return True

    def exit_application(self) -> None:
        """Shut down safely and stop the resident Qt event loop."""
        if self.shutdown():
            self.application.quit()


def create_runtime(
    arguments: Sequence[str],
    config_path: Path | None = None,
    *,
    desktop_integration: bool = False,
) -> ApplicationRuntime:
    """Construct the complete desktop object graph from concrete implementations."""
    config_manager = ConfigManager(config_path)
    logger = initialize_logging(config_manager.config_path.parent / "logs", "INFO")
    logger.info("Application startup started")
    config = config_manager.load()
    set_log_level(config.log_level)

    existing_application = cast(QApplication | None, QApplication.instance())
    application = existing_application or QApplication(list(arguments))
    application.setApplicationName("ICU Patient Tracker")
    application.setOrganizationName("ICU Patient Tracker")
    application.setQuitOnLastWindowClosed(not desktop_integration)
    application_icon = load_application_icon()
    if application_icon.isNull():
        logger.warning("Packaged application icon could not be loaded")
    else:
        application.setWindowIcon(application_icon)

    theme_manager = ThemeManager()
    theme_manager.apply(application, config.theme)
    database = DatabaseManager(config.database_path)
    database.initialize()
    dispatcher = InProcessEventDispatcher()
    unit_of_work = cast(UnitOfWorkFactory, database.unit_of_work)
    reminders_service = ReminderService(unit_of_work, dispatcher)
    backup_service = BackupService(
        BackupManager(
            config.database_path,
            config.backup_directory,
            retention_count=config.backup_retention_count,
        ),
        dispatcher,
        prepare_for_replace=database.dispose,
        reopen_after_replace=database.initialize,
    )
    clipboard_writer = QtClipboardAdapter(application)
    recovery_service = RecoveryService(
        RecoveryStore(config_manager.config_path.parent / "recovery.json"),
        dispatcher,
        debounce_seconds=config.autosave_debounce_seconds,
    )
    services = ServiceBundle(
        patients=PatientService(unit_of_work, dispatcher),
        days=HospitalDayService(unit_of_work, dispatcher),
        problems=ProblemService(unit_of_work, dispatcher),
        tasks=TaskService(unit_of_work, dispatcher),
        diagnostic_results=DiagnosticResultService(unit_of_work, dispatcher),
        instrumentation=InstrumentationService(unit_of_work, dispatcher),
        soap=SOAPService(unit_of_work, dispatcher),
        sandbox=SandboxService(unit_of_work, dispatcher),
        search=SearchService(unit_of_work, dispatcher),
        settings=SettingsService(config_manager, dispatcher),
        reminders=reminders_service,
        backup=backup_service,
        clipboard=ClipboardService(unit_of_work, clipboard_writer, dispatcher),
        analytics=AnalyticsService(unit_of_work, clipboard_writer),
        recovery=recovery_service,
    )
    controller = PresentationController(services)
    autosave_coordinator = AutosaveCoordinator(
        AutosaveController(
            controller.commit_pending,
            debounce_seconds=config.autosave_debounce_seconds,
            retry_seconds=config.autosave_retry_seconds,
        ),
        dispatcher,
    )
    controller.attach_autosave(autosave_coordinator)
    qt_events = QtEventAdapter(dispatcher)
    qt_autosave = QtAutosaveAdapter(autosave_coordinator)
    shared_tray_icon: QSystemTrayIcon | None = None
    notification_sink: QtSystemTrayNotificationSink | None = None
    if desktop_integration:
        shared_tray_icon = QSystemTrayIcon()
        shared_tray_icon.setIcon(application_icon)
        notification_sink = QtSystemTrayNotificationSink(shared_tray_icon)
    qt_reminders = QtReminderAdapter(reminders_service, notification_sink=notification_sink)
    qt_recovery = QtRecoveryAdapter(recovery_service)
    window = MainWindow(
        controller,
        qt_events,
        qt_autosave,
        qt_reminders,
        qt_recovery,
        theme_manager,
    )
    window.setWindowIcon(application_icon)
    runtime = ApplicationRuntime(
        application,
        window,
        database,
        config,
        logger,
        controller,
        qt_events,
        qt_autosave,
        qt_reminders,
        qt_recovery,
    )
    window.exit_requested.connect(runtime.exit_application)
    runtime.sync = QtSyncAdapter(
        ClinicalSyncService(database.unit_of_work), controller, window, config_manager.config_path
    )
    if desktop_integration and shared_tray_icon is not None:
        runtime.tray = DesktopTrayAdapter(
            shared_tray_icon,
            is_window_visible=window.is_shell_visible,
            is_window_pinned=lambda: window.is_main_pinned,
            toggle_window=window.toggle_application_visibility,
            show_task_board=window.toggle_task_board,
            set_window_pinned=window.set_main_pin,
            exit_application=runtime.exit_application,
        )
        runtime.global_hotkeys = GlobalHotkeyManager(
            {
                "toggle_application": window.toggle_application_visibility,
                "toggle_task_board": window.toggle_task_board,
                "capture_diagnostic_result": window.show_diagnostic_result_capture,
            },
            application=application,
            logger=logger,
        )
        runtime.global_hotkeys.start()
        if runtime.tray.is_available or runtime.global_hotkeys.registered_labels:
            window.enable_tray_residency()
        else:
            logger.warning(
                "Tray residency disabled because neither the system tray nor global hotkeys "
                "are available"
            )
    logger.info("Application startup complete")
    return runtime


def run_application(arguments: Sequence[str]) -> int:
    """Run the Qt event loop and guarantee controlled resource shutdown."""
    runtime: ApplicationRuntime | None = None
    instance: SingleInstanceCoordinator | None = None
    try:
        existing_application = cast(QApplication | None, QApplication.instance())
        application = existing_application or QApplication(list(arguments))
        application.setApplicationName("ICU Patient Tracker")
        application.setOrganizationName("ICU Patient Tracker")
        data_directory = ConfigManager().config_path.parent
        data_directory.mkdir(parents=True, exist_ok=True)
        instance = SingleInstanceCoordinator(data_directory)
        if not instance.acquire_or_notify():
            return 0
        runtime = create_runtime(arguments, desktop_integration=True)
        instance.activation_requested.connect(runtime.window.activate_main_window)
        runtime.window.show()
        return runtime.application.exec()
    except Exception:
        logging.getLogger("icu_patient_tracker").exception("Unhandled application exception")
        return 1
    finally:
        if runtime is not None:
            runtime.shutdown()
        if instance is not None:
            instance.close()
