"""Persistence-related application configuration tests."""

from pathlib import Path

from icu_patient_tracker.app.config import AppConfig, ConfigManager


def test_persistence_paths_and_scheduling_settings_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    manager = ConfigManager(config_path)
    manager.save(
        AppConfig(
            database_path=Path("data/tracker.sqlite3"),
            backup_directory=Path("safe-backups"),
            backup_retention_count=7,
            autosave_debounce_seconds=1.25,
            autosave_retry_seconds=8,
            soap_daytime_resident="Dr. Day",
            minimize_after_copy=False,
        )
    )

    loaded = manager.load()
    assert loaded.database_path == tmp_path / "data/tracker.sqlite3"
    assert loaded.backup_directory == tmp_path / "safe-backups"
    assert loaded.backup_retention_count == 7
    assert loaded.autosave_debounce_seconds == 1.25
    assert loaded.autosave_retry_seconds == 8
    assert loaded.soap_daytime_resident == "Dr. Day"
    assert loaded.minimize_after_copy is False


def test_macos_default_data_directory_uses_application_support(monkeypatch) -> None:
    monkeypatch.setattr("icu_patient_tracker.app.config.sys.platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/Users/tester")))

    assert ConfigManager._get_data_directory() == (
        Path("/Users/tester/Library/Application Support/ICUPatientTracker")
    )
