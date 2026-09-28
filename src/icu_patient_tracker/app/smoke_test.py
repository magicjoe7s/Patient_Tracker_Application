"""Isolated startup verification for an installed or packaged application."""

from __future__ import annotations

import os
from pathlib import Path

from icu_patient_tracker.app.config import AppConfig, ConfigManager


def run_smoke_test(work_directory: Path) -> int:
    """Initialize and shut down using disposable paths supplied by the caller."""
    root = work_directory.expanduser().resolve()
    config_path = root / "smoke-config.json"
    database_path = root / "smoke.sqlite3"
    backup_directory = root / "backups"
    if config_path.exists() or database_path.exists() or backup_directory.exists():
        raise RuntimeError("The smoke-test work directory contains prior smoke-test artifacts.")
    root.mkdir(parents=True, exist_ok=True)
    ConfigManager(config_path).save(
        AppConfig(
            database_path=database_path,
            backup_directory=backup_directory,
            autosave_debounce_seconds=0,
        )
    )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from icu_patient_tracker.app.bootstrap import create_runtime

    try:
        runtime = create_runtime(["icu-patient-tracker", "--smoke-test"], config_path)
        try:
            runtime.database.verify_connection()
            if runtime.database.sqlite_settings()["foreign_keys"] != 1:
                raise RuntimeError("Packaged SQLite foreign-key verification failed.")
        finally:
            if not runtime.shutdown():
                raise RuntimeError("Packaged application did not shut down cleanly.")
    except Exception as error:
        (root / "smoke-error.txt").write_text(
            f"{type(error).__name__}: {error}\n",
            encoding="utf-8",
        )
        raise
    return 0
