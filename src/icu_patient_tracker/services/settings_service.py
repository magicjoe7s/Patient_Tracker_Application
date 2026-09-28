"""Validated device-local configuration use cases."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from icu_patient_tracker.app.config import AppConfig, ConfigManager
from icu_patient_tracker.services.events import EventPublisher, NullEventPublisher, SettingsChanged
from icu_patient_tracker.services.exceptions import SettingsValidationError


class SettingsService:
    """Load, update, and reset non-clinical settings through one boundary."""

    def __init__(self, manager: ConfigManager, publisher: EventPublisher | None = None) -> None:
        self._manager = manager
        self._publisher = publisher or NullEventPublisher()

    def get(self) -> AppConfig:
        try:
            return self._manager.load()
        except (ValueError, RuntimeError) as error:
            raise SettingsValidationError(str(error)) from error

    def update(self, **changes: Any) -> AppConfig:
        unknown = set(changes) - set(AppConfig.__dataclass_fields__)
        if unknown:
            raise SettingsValidationError(f"Unknown setting(s): {', '.join(sorted(unknown))}.")
        try:
            updated = replace(self.get(), **changes)
            self._validate(updated)
            self._manager.save(updated)
        except (TypeError, ValueError, RuntimeError) as error:
            raise SettingsValidationError(str(error)) from error
        self._publisher.publish(SettingsChanged("device", "updated"))
        return updated

    def reset(self) -> AppConfig:
        defaults = self._manager.default_config()
        self._manager.save(defaults)
        self._publisher.publish(SettingsChanged("device", "reset"))
        return defaults

    @staticmethod
    def _validate(config: AppConfig) -> None:
        if not config.theme.strip() or not config.log_level.strip():
            raise SettingsValidationError("Theme and log level must be non-empty.")
        if config.backup_retention_count < 1:
            raise SettingsValidationError("Backup retention must be at least 1.")
        if config.autosave_debounce_seconds < 0 or config.autosave_retry_seconds < 0:
            raise SettingsValidationError("Autosave timing must not be negative.")
        if "\n" in config.soap_daytime_resident:
            raise SettingsValidationError("SOAP daytime resident must be single-line text.")
        if not isinstance(config.minimize_after_copy, bool):
            raise SettingsValidationError("Minimize after copy must be a boolean.")
