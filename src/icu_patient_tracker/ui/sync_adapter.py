"""Background network jobs and GUI-thread reconciliation for automatic sync."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from icu_patient_tracker.services.clinical_sync_service import ClinicalSyncService, SyncConflict
from icu_patient_tracker.sync.credentials import create_token_store
from icu_patient_tracker.sync.project import (
    DEVICES,
    OWNER_ID,
    PROJECT_URL,
    PUBLISHABLE_KEY,
    WORKSPACE_ID,
)
from icu_patient_tracker.sync.supabase_auth import SupabaseAuth
from icu_patient_tracker.sync.supabase_gateway import SupabaseSyncGateway
from icu_patient_tracker.sync.validation import validate_change_page
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.sync_preview import describe_snapshot


class _NetworkJob(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], Any], parent: QObject) -> None:
        super().__init__(parent)
        self.operation = operation

    def run(self) -> None:
        try:
            self.result_ready.emit(self.operation())
        except Exception as error:
            # Never surface request bodies, tokens or database parameters.
            from icu_patient_tracker.sync.supabase_auth import SignInRequired

            self.failed.emit(
                "Sign in required"
                if isinstance(error, SignInRequired)
                else "Offline or sync unavailable; changes remain saved locally"
            )
        finally:
            self.operation = lambda: None


class QtSyncAdapter(QObject):
    """Network work never runs on Qt's UI thread or holds an SQLite transaction."""

    def __init__(
        self,
        service: ClinicalSyncService,
        controller: PresentationController,
        window: Any,
        config_path: Path,
    ) -> None:
        super().__init__(window)
        self.service = service
        self.controller = controller
        self.window = window
        self.path = config_path.parent / "sync_connection.json"
        self.device_name = "Laptop"
        self.enabled = False
        self.auth: SupabaseAuth | None = None
        self.gateway: SupabaseSyncGateway | None = None
        self.job: _NetworkJob | None = None
        self.stopped = False
        self.reviewing = False
        self.button = QPushButton("Sync: Set up")
        self.button.setAccessibleName("Sync status and settings")
        self.button.clicked.connect(self.show_settings)
        window.statusBar().addPermanentWidget(self.button)
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1500)
        self.save_timer.timeout.connect(self.tick)
        controller.save_status_changed.connect(self._saved)
        controller.operation_status.connect(lambda _status: self.save_timer.start())
        try:
            if self.path.exists():
                config = json.loads(self.path.read_text(encoding="utf-8"))
                self.device_name = config["device"]
                if self.device_name not in DEVICES:
                    raise ValueError("Unknown device")
                self.enabled = config.get("enabled") is True
                self._connect_objects()
                self.button.setText("Sync: Paused")
                if self.enabled:
                    self.button.setText("Sync: Connecting")
                    QTimer.singleShot(2000, self.tick)
        except (OSError, ValueError, KeyError):
            self.enabled = False
            self.button.setText("Sync: Setup required")

    def _connect_objects(self) -> None:
        self.auth = SupabaseAuth(
            PROJECT_URL,
            PUBLISHABLE_KEY,
            OWNER_ID,
            create_token_store(f"{WORKSPACE_ID}/{DEVICES[self.device_name]}"),
        )
        self.gateway = SupabaseSyncGateway(
            PROJECT_URL,
            publishable_key=PUBLISHABLE_KEY,
            access_token_provider=self.auth.access_token,
            workspace_id=UUID(WORKSPACE_ID),
            device_id=UUID(DEVICES[self.device_name]),
        )

    def _saved(self, status: str) -> None:
        if status == "Saved":
            self.save_timer.start()

    def _save_connection(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"device": self.device_name, "enabled": self.enabled}), encoding="utf-8"
        )
        temporary.replace(self.path)

    def _initialize_local(self) -> None:
        self.service.initialize(
            self.device_name, UUID(DEVICES[self.device_name]), UUID(WORKSPACE_ID)
        )

    def _start_job(self, operation: Callable[[], Any], success: Callable[[Any], None]) -> None:
        job = _NetworkJob(operation, self)
        self.job = job
        job.result_ready.connect(lambda result: success(result) if not self.stopped else None)
        job.failed.connect(lambda text: self.button.setText("Sync: " + text))
        job.finished.connect(self._job_finished)
        job.start()

    def _job_finished(self) -> None:
        if self.job is not None:
            self.job.deleteLater()
            self.job = None

    def tick(self) -> None:
        if self.stopped or not self.enabled or self.job is not None or self.reviewing:
            return
        if self.controller.context.is_dirty:
            return  # The normal autosave debounce will commit before a later tick.
        try:
            operations, cursor = self.service.prepare(UUID(DEVICES[self.device_name]))
            gateway = self.gateway
            if gateway is None:
                return
            self.button.setText("Sync: Syncing")

            def exchange() -> Any:
                results = (
                    gateway.push(
                        workspace_id=WORKSPACE_ID,
                        device_id=DEVICES[self.device_name],
                        operations=operations,
                    )
                    if operations
                    else ()
                )
                page = gateway.changes(workspace_id=WORKSPACE_ID, after=cursor)
                validate_change_page(cursor, page.changes, page.next_cursor, page.has_more)
                return results, page

            def finish(result: Any) -> None:
                try:
                    # Save edits typed during the request before applying remote data.
                    if not self.controller.flush_pending():
                        self.button.setText("Sync: Waiting for local save")
                        return
                    results, page = result
                    changed, queued, conflicts = self.service.finish(
                        operations, results, page, UUID(DEVICES[self.device_name])
                    )
                    self.button.setText(
                        f"Sync: {conflicts} conflicts"
                        if conflicts
                        else f"Sync: {queued} queued"
                        if queued
                        else "Sync: Syncing"
                        if page.has_more
                        else "Sync: Synced"
                    )
                    if changed:
                        self._refresh_views()
                    if page.has_more or (queued and not conflicts):
                        QTimer.singleShot(1000, self.tick)
                except Exception:
                    self.button.setText("Sync: Review needed; local data preserved")

            self._start_job(exchange, finish)
        except Exception:
            self.button.setText("Sync: Review needed; local data preserved")

    def _refresh_views(self) -> None:
        context = self.controller.context
        patient_id, day_id = self.service.selection(context.patient_id, context.hospital_day_id)
        if patient_id != context.patient_id:
            self.controller.select_patient(patient_id)
        elif day_id != context.hospital_day_id:
            context.select_day(day_id)
        self.controller.context_changed.emit(context)
        self.window.patient_panel.refresh()
        self.window.workspace.refresh()
        self.window._refresh_task_views("", "synced")

    def show_settings(self) -> None:
        if self.job is not None:
            QMessageBox.information(
                self.window, "Sync", "A sync request is finishing. Try again shortly."
            )
            return
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Sync between computers")
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "Sign in once on each computer with your tracker account.\n"
                "Connecting uploads this database's patients to your Supabase project."
            )
        )
        form = QFormLayout()
        device = QComboBox()
        device.addItems(list(DEVICES))
        device.setCurrentText(self.device_name)
        email = QLineEdit()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("This computer", device)
        form.addRow("Tracker email", email)
        form.addRow("Tracker password", password)
        layout.addLayout(form)
        label = QLabel(self.button.text())
        label.setWordWrap(True)
        layout.addWidget(label)
        connect = QPushButton("Connect and remember login")
        sync_now = QPushButton("Sync now")
        sync_now.setEnabled(self.enabled)
        pause = QPushButton("Pause syncing" if self.enabled else "Resume syncing")
        review = QPushButton("Review conflicts")
        signout = QPushButton("Forget login on this computer")
        for button in (sync_now, connect, pause, review, signout):
            layout.addWidget(button)

        def login() -> None:
            if not email.text().strip() or not password.text():
                label.setText("Enter your tracker email and password.")
                return
            old_name = self.device_name
            self.device_name = device.currentText()
            try:
                self._initialize_local()
                self._connect_objects()
            except Exception as error:
                self.device_name = old_name
                label.setText(str(error))
                return
            auth, gateway = self.auth, self.gateway
            if auth is None or gateway is None:
                return
            login_email, login_password = email.text(), password.text()
            password.clear()
            self.enabled = False
            dialog.accept()
            self.button.setText("Sync: Signing in")

            def authenticate() -> None:
                auth.sign_in(login_email, login_password)
                gateway.health()

            def connected(_result: Any) -> None:
                self.enabled = True
                self._save_connection()
                self.button.setText("Sync: Connected")
                QTimer.singleShot(1000, self.tick)

            self._start_job(authenticate, connected)

        def toggle() -> None:
            if self.auth is None:
                label.setText("Sign in first.")
                return
            self.enabled = not self.enabled
            self._save_connection()
            self.button.setText("Sync: Connecting" if self.enabled else "Sync: Paused")
            dialog.accept()
            if self.enabled:
                QTimer.singleShot(0, self.tick)

        def synchronize() -> None:
            dialog.accept()
            QTimer.singleShot(0, self.tick)

        def forget() -> None:
            if self.auth is not None:
                self.auth.sign_out()
            self.enabled = False
            self._save_connection()
            self.button.setText("Sync: Signed out")
            dialog.accept()

        connect.clicked.connect(login)
        sync_now.clicked.connect(synchronize)
        pause.clicked.connect(toggle)
        signout.clicked.connect(forget)

        def review_all() -> None:
            dialog.accept()
            self.review_conflicts()

        review.clicked.connect(review_all)
        self.reviewing = True
        try:
            dialog.exec()
        finally:
            self.reviewing = False

    def review_conflicts(self) -> None:
        if not self.controller.flush_pending():
            return
        conflicts = self.service.conflicts()
        if not conflicts:
            QMessageBox.information(self.window, "Sync conflicts", "No unresolved conflicts.")
            return
        self.reviewing = True
        try:
            for conflict in conflicts:
                self._review_one(conflict)
        finally:
            self.reviewing = False

    def _review_one(self, conflict: SyncConflict) -> None:
        local, revision = self.service.local_version(conflict.entity_id)
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Review patient sync conflict")
        dialog.resize(1000, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "Choose which complete patient version to use. Both versions remain\n"
                "in local conflict history. A later server edit will require review again."
            )
        )
        columns = QHBoxLayout()
        for title, payload in (
            ("This computer", local),
            ("Other computer / server", conflict.server_payload),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText(describe_snapshot(payload))
            column.addWidget(text)
            columns.addLayout(column)
        layout.addLayout(columns)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        keep_local = buttons.addButton("Keep this computer", QDialogButtonBox.ButtonRole.AcceptRole)
        keep_server = buttons.addButton(
            "Use server version", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.rejected.connect(dialog.reject)

        def resolve(local_choice: bool) -> None:
            try:
                if not self.controller.flush_pending():
                    return
                self.service.resolve(conflict, local_choice, revision)
                self._refresh_views()
                dialog.accept()
            except Exception:
                QMessageBox.warning(
                    dialog, "Conflict changed", "Reopen this conflict to review the latest values."
                )

        keep_local.clicked.connect(lambda: resolve(True))
        keep_server.clicked.connect(lambda: resolve(False))
        layout.addWidget(buttons)
        dialog.exec()

    def stop(self) -> None:
        self.stopped = True
        self.timer.stop()
        self.save_timer.stop()
        if self.job is not None:
            self.job.wait()  # Only during shutdown; HTTP requests have finite timeouts.
