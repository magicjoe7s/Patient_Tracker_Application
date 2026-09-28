"""Device-local settings dialog."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.save_shortcut import bind_standard_save


class SettingsDialog(QDialog):
    """Edit only settings already validated by SettingsService."""

    applied = Signal()

    def __init__(self, controller: PresentationController, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._controller = controller
        self.setWindowTitle("Settings")
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.autosave_delay = QDoubleSpinBox()
        self.autosave_delay.setRange(0, 30)
        self.autosave_delay.setSuffix(" seconds")
        self.retention = QSpinBox()
        self.retention.setRange(1, 100)
        self.storage = QLabel()
        self.storage.setWordWrap(True)
        self.soap_daytime_resident = QLineEdit()
        self.soap_daytime_resident.setPlaceholderText("Daytime primary ICU resident")
        self.minimize_after_copy = QCheckBox("Minimize after a successful SOAP copy")
        form = QFormLayout()
        form.addRow("Theme", self.theme)
        form.addRow("Log level", self.log_level)
        form.addRow("Autosave delay", self.autosave_delay)
        form.addRow("Backup retention", self.retention)
        form.addRow("SOAP daytime resident", self.soap_daytime_resident)
        form.addRow("EMR handoff", self.minimize_after_copy)
        form.addRow("Device-local storage", self.storage)
        self.reset_button = QPushButton("Reset defaults")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bind_standard_save(buttons)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("These preferences are device-local, not clinical records."))
        layout.addWidget(self.reset_button)
        layout.addWidget(buttons)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.reset_button.clicked.connect(self._reset)
        self._load()

    def _load(self) -> None:
        config = self._controller.settings()
        if config is None:
            return
        self.theme.setCurrentText(config.theme)
        self.log_level.setCurrentText(config.log_level)
        self.autosave_delay.setValue(config.autosave_debounce_seconds)
        self.retention.setValue(config.backup_retention_count)
        self.soap_daytime_resident.setText(config.soap_daytime_resident)
        self.minimize_after_copy.setChecked(config.minimize_after_copy)
        self.storage.setText(str(config.database_path))

    def _save(self) -> None:
        updated = self._controller.update_settings(
            theme=self.theme.currentText(),
            log_level=self.log_level.currentText(),
            autosave_debounce_seconds=self.autosave_delay.value(),
            backup_retention_count=self.retention.value(),
            soap_daytime_resident=self.soap_daytime_resident.text(),
            minimize_after_copy=self.minimize_after_copy.isChecked(),
        )
        if updated is not None:
            self.applied.emit()
            self.accept()
        else:
            self._load()

    def _reset(self) -> None:
        if self._controller.reset_settings() is not None:
            self._load()
            self.applied.emit()
