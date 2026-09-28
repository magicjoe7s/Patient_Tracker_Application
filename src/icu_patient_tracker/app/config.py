"""Load and persist non-clinical application settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    """Non-clinical settings required to initialize the application."""

    theme: str = "dark"
    log_level: str = "INFO"
    database_path: Path = Path("patient_tracker.sqlite3")
    backup_directory: Path = Path("backups")
    backup_retention_count: int = 10
    autosave_debounce_seconds: float = 2.0
    autosave_retry_seconds: float = 5.0
    soap_daytime_resident: str = ""
    minimize_after_copy: bool = True
    sync_enabled: bool = False
    sync_base_url: str = "http://127.0.0.1:8765"
    sync_workspace_id: str = ""
    sync_device_name: str = ""
    user_preferences: dict[str, object] = field(default_factory=dict)
    future_settings: dict[str, object] = field(default_factory=dict)


class ConfigManager:
    """Own configuration file location, validation, loading, and saving."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._data_directory = self._get_data_directory()
        self._config_path = config_path or self._data_directory / "config.json"

    @property
    def config_path(self) -> Path:
        """Return the configuration file used by this manager."""
        return self._config_path

    def load(self) -> AppConfig:
        """Load settings, creating a default file on first use."""
        if not self._config_path.exists():
            config = self._default_config()
            self.save(config)
            return config

        try:
            raw_data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except OSError as error:
            raise RuntimeError(f"Unable to read configuration: {self._config_path}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"Configuration is not valid JSON: {self._config_path}") from error

        if not isinstance(raw_data, dict):
            raise ValueError("Configuration must contain a JSON object.")
        return self._parse_config(raw_data)

    def save(self, config: AppConfig) -> None:
        """Persist settings atomically to avoid partial configuration files."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(config)
        payload["database_path"] = str(config.database_path)
        payload["backup_directory"] = str(config.backup_directory)
        temporary_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary_path.replace(self._config_path)
        except OSError as error:
            raise RuntimeError(f"Unable to save configuration: {self._config_path}") from error

    def default_config(self) -> AppConfig:
        """Return fresh defaults resolved for this manager's data location."""
        return self._default_config()

    def _default_config(self) -> AppConfig:
        return AppConfig(
            database_path=self._data_directory / "patient_tracker.sqlite3",
            backup_directory=self._data_directory / "backups",
        )

    def _parse_config(self, raw_data: dict[str, Any]) -> AppConfig:
        theme = raw_data.get("theme", "dark")
        log_level = raw_data.get("log_level", "INFO")
        database_path = raw_data.get(
            "database_path", self._data_directory / "patient_tracker.sqlite3"
        )
        backup_directory = raw_data.get("backup_directory", self._data_directory / "backups")
        backup_retention_count = raw_data.get("backup_retention_count", 10)
        autosave_debounce_seconds = raw_data.get("autosave_debounce_seconds", 2.0)
        if autosave_debounce_seconds == 0.7:
            autosave_debounce_seconds = 2.0
        autosave_retry_seconds = raw_data.get("autosave_retry_seconds", 5.0)
        soap_daytime_resident = raw_data.get("soap_daytime_resident", "")
        minimize_after_copy = raw_data.get("minimize_after_copy", True)
        sync_enabled = raw_data.get("sync_enabled", False)
        sync_base_url = raw_data.get("sync_base_url", "http://127.0.0.1:8765")
        sync_workspace_id = raw_data.get("sync_workspace_id", "")
        sync_device_name = raw_data.get("sync_device_name", "")
        user_preferences = raw_data.get("user_preferences", {})
        future_settings = raw_data.get("future_settings", {})

        if not isinstance(theme, str) or not theme:
            raise ValueError("The theme setting must be a non-empty string.")
        if not isinstance(log_level, str) or not log_level:
            raise ValueError("The log_level setting must be a non-empty string.")
        if not isinstance(database_path, (str, Path)) or not str(database_path):
            raise ValueError("The database_path setting must be a non-empty path.")
        if not isinstance(backup_directory, (str, Path)) or not str(backup_directory):
            raise ValueError("The backup_directory setting must be a non-empty path.")
        if not isinstance(backup_retention_count, int) or backup_retention_count < 1:
            raise ValueError("The backup_retention_count setting must be at least 1.")
        if not isinstance(autosave_debounce_seconds, (int, float)) or autosave_debounce_seconds < 0:
            raise ValueError("The autosave_debounce_seconds setting must not be negative.")
        if not isinstance(autosave_retry_seconds, (int, float)) or autosave_retry_seconds < 0:
            raise ValueError("The autosave_retry_seconds setting must not be negative.")
        if not isinstance(soap_daytime_resident, str) or "\n" in soap_daytime_resident:
            raise ValueError("The SOAP daytime resident must be single-line text.")
        if not isinstance(minimize_after_copy, bool):
            raise ValueError("The minimize_after_copy setting must be a boolean.")
        if not isinstance(sync_enabled, bool):
            raise ValueError("The sync_enabled setting must be a boolean.")
        if not isinstance(sync_base_url, str) or not sync_base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("The sync_base_url setting must be an HTTP or HTTPS URL.")
        if not isinstance(sync_workspace_id, str):
            raise ValueError("The sync_workspace_id setting must be text.")
        if not isinstance(sync_device_name, str) or "\n" in sync_device_name:
            raise ValueError("The sync_device_name setting must be single-line text.")
        if not isinstance(user_preferences, dict):
            raise ValueError("The user_preferences setting must be a JSON object.")
        if not isinstance(future_settings, dict):
            raise ValueError("The future_settings setting must be a JSON object.")

        resolved_database_path = Path(database_path).expanduser()
        if not resolved_database_path.is_absolute():
            resolved_database_path = self._config_path.parent / resolved_database_path
        resolved_backup_directory = Path(backup_directory).expanduser()
        if not resolved_backup_directory.is_absolute():
            resolved_backup_directory = self._config_path.parent / resolved_backup_directory

        return AppConfig(
            theme=theme,
            log_level=log_level.upper(),
            database_path=resolved_database_path,
            backup_directory=resolved_backup_directory,
            backup_retention_count=backup_retention_count,
            autosave_debounce_seconds=float(autosave_debounce_seconds),
            autosave_retry_seconds=float(autosave_retry_seconds),
            soap_daytime_resident=" ".join(soap_daytime_resident.split()),
            minimize_after_copy=minimize_after_copy,
            sync_enabled=sync_enabled,
            sync_base_url=sync_base_url.rstrip("/"),
            sync_workspace_id=sync_workspace_id.strip(),
            sync_device_name=" ".join(sync_device_name.split()),
            user_preferences=user_preferences,
            future_settings=future_settings,
        )

    @staticmethod
    def _get_data_directory() -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "ICUPatientTracker"
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "ICUPatientTracker"
        return Path.home() / ".icu_patient_tracker"
