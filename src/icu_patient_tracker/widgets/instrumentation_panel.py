"""Structured selected-day devices with a lossless SOAP-compatible text projection."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceStatus, DeviceType
from icu_patient_tracker.services.instrumentation_service import device_line
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.text_refresh import set_plain_text_safely

_DEVICE_CHOICES: tuple[tuple[str, DeviceType, str], ...] = (
    ("Peripheral IVC", DeviceType.PERIPHERAL_IV_CATHETER, ""),
    ("Central line (jugular)", DeviceType.CENTRAL_VENOUS_CATHETER, "jugular"),
    ("Central line (saphenous)", DeviceType.CENTRAL_VENOUS_CATHETER, "saphenous"),
    ("Chest tube", DeviceType.CHEST_TUBE, ""),
    ("Urinary catheter", DeviceType.URINARY_CATHETER, ""),
    ("Drain", DeviceType.ABDOMINAL_DRAIN, ""),
    ("Fecal foley", DeviceType.FECAL_FOLEY, ""),
)


class InstrumentationPanel(QWidget):
    """Manage durable devices by checkbox and preserve free-text interoperability."""

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self._loaded_generation = -1
        self._base_values: dict[str, str] = {}
        self._devices: dict[UUID, Device] = {}
        self._rebuilding = False
        self.checkboxes: dict[str, QCheckBox] = {}

        guidance = QLabel(
            "Check a device to record its size, location, and placement date. "
            "Active devices carry to the next hospital day."
        )
        guidance.setWordWrap(True)
        choices = QGridLayout()
        for index, (label, _device_type, _location_hint) in enumerate(_DEVICE_CHOICES):
            checkbox = QCheckBox(label)
            checkbox.setObjectName("device_" + label.casefold().replace(" ", "_"))
            checkbox.toggled.connect(
                lambda checked, label=label: self._device_toggled(label, checked)
            )
            self.checkboxes[label] = checkbox
            choices.addWidget(checkbox, index // 2, index % 2)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("instrumentationText")
        self.editor.setAccessibleName("Devices for selected hospital day")
        self.editor.setPlaceholderText(
            "Structured devices appear here. Additional instrumentation may be entered "
            "one item per line."
        )
        layout = QVBoxLayout(self)
        layout.addWidget(guidance)
        layout.addLayout(choices)
        layout.addWidget(QLabel("Instrumentation details (SOAP-synchronized)"))
        layout.addWidget(self.editor, 1)
        self.editor.textChanged.connect(self._mark_dirty)

    def refresh(self, *, force: bool = False) -> None:
        generation = self._controller.context.generation
        replace_focused = force or generation != self._loaded_generation
        devices = self._controller.devices() if self._controller.context.hospital_day_id else ()
        active = tuple(device for device in devices if device.status is DeviceStatus.ACTIVE)
        self._devices = {device.id: device for device in active}
        value = "\n".join(device_line(device) for device in active)
        self.editor.blockSignals(True)
        set_plain_text_safely(self.editor, value, force=replace_focused)
        self.editor.blockSignals(False)
        self._rebuilding = True
        try:
            for label, device_type, hint in _DEVICE_CHOICES:
                self.checkboxes[label].setChecked(
                    any(self._matches(device, device_type, hint) for device in active)
                )
        finally:
            self._rebuilding = False
        self._loaded_generation = generation
        self._base_values = self.recovery_values()
        self.setEnabled(self._controller.context.hospital_day_id is not None)

    def save(self) -> bool:
        if self._loaded_generation != self._controller.context.generation:
            return False
        lines = tuple(self.editor.toPlainText().splitlines())
        saved = self._controller.replace_device_lines(lines)
        if saved is None:
            return False
        self._base_values = self.recovery_values()
        self._controller.editor_saved("instrumentation")
        return True

    def recovery_values(self) -> dict[str, str]:
        return {"lines": self.editor.toPlainText()}

    def apply_recovery(self, values: dict[str, str]) -> None:
        set_plain_text_safely(self.editor, values.get("lines", ""), force=True)
        self._mark_dirty()

    def _device_toggled(self, label: str, checked: bool) -> None:
        if self._rebuilding:
            return
        _, device_type, hint = next(item for item in _DEVICE_CHOICES if item[0] == label)
        matching = next(
            (
                device
                for device in self._devices.values()
                if self._matches(device, device_type, hint)
            ),
            None,
        )
        if not checked:
            if matching is not None:
                self._controller.discontinue_device(matching.id)
            return
        if matching is not None:
            return

        size, accepted = QInputDialog.getText(self, f"Add {label}", "Size:")
        if not accepted:
            self._restore_checkbox(label)
            return
        location, accepted = QInputDialog.getText(
            self, f"Add {label}", "Location:", text=hint
        )
        if not accepted or not location.strip():
            self._restore_checkbox(label)
            return
        placed_text, accepted = QInputDialog.getText(
            self,
            f"Add {label}",
            "Date placed (YYYY-MM-DD):",
            text=date.today().isoformat(),
        )
        if not accepted:
            self._restore_checkbox(label)
            return
        try:
            placed_date = date.fromisoformat(placed_text.strip())
        except ValueError:
            self._controller.error_raised.emit(
                "Invalid placement date", "Enter the date as YYYY-MM-DD."
            )
            self._restore_checkbox(label)
            return
        local_zone = datetime.now().astimezone().tzinfo
        placed_at = datetime.combine(placed_date, time(hour=8), tzinfo=local_zone)
        if self._controller.add_device(
            device_type, location.strip(), placed_at, size=size.strip() or None
        ) is None:
            self._restore_checkbox(label)

    def _restore_checkbox(self, label: str) -> None:
        self._rebuilding = True
        self.checkboxes[label].setChecked(False)
        self._rebuilding = False

    @staticmethod
    def _matches(device: Device, device_type: DeviceType, hint: str) -> bool:
        if device.device_type is not device_type:
            return False
        if not hint:
            return True
        return hint in device.anatomical_location.casefold()

    def _mark_dirty(self) -> None:
        self._controller.mark_editor_dirty(
            "instrumentation",
            self._save_pending,
            base_values=self._base_values,
            draft_values=self.recovery_values,
        )

    def _save_pending(self) -> None:
        if not self.save():
            raise RuntimeError("Instrumentation text could not be saved.")
