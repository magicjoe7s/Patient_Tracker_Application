"""Smoke tests for foundation initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import QToolBar

from icu_patient_tracker.app.bootstrap import create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def test_application_infrastructure_initializes(tmp_path: Path) -> None:
    """The complete foundation starts without creating a clinical schema."""
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            theme="dark",
            log_level="DEBUG",
            database_path=tmp_path / "tracker.sqlite3",
        )
    )

    runtime = create_runtime(["icu-patient-tracker"], config_path)
    try:
        runtime.window.show()
        runtime.application.processEvents()
        assert runtime.window.windowTitle() == "ICU Patient Tracker"
        assert runtime.window.isVisible()
        assert runtime.window.centralWidget() is not None
        assert runtime.window.menuBar().actions()
        assert runtime.window.findChild(QToolBar, "mainToolbar") is not None
        assert (tmp_path / "tracker.sqlite3").exists()
        with sqlite3.connect(tmp_path / "tracker.sqlite3") as connection:
            table_names = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        assert ("patients",) in table_names
        assert ("alembic_version",) in table_names
    finally:
        runtime.shutdown()
    assert not runtime.window.isVisible()
