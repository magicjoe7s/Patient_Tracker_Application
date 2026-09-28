"""Installed-entrypoint smoke verification for release packaging."""

from pathlib import Path

from icu_patient_tracker.main import main
from icu_patient_tracker.persistence.migration_manager import (
    CURRENT_SCHEMA_REVISION,
    MigrationManager,
)


def test_release_smoke_uses_only_disposable_explicit_paths(tmp_path: Path) -> None:
    work_directory = tmp_path / "release-smoke"

    assert main(["icu-patient-tracker", "--smoke-test", str(work_directory)]) == 0

    database = work_directory / "smoke.sqlite3"
    assert database.is_file()
    assert MigrationManager(database).current_revision() == CURRENT_SCHEMA_REVISION
    assert (work_directory / "smoke-config.json").is_file()
    assert not (work_directory / "smoke-error.txt").exists()


def test_release_smoke_refuses_to_reuse_prior_artifacts(tmp_path: Path) -> None:
    work_directory = tmp_path / "release-smoke"
    work_directory.mkdir()
    (work_directory / "smoke.sqlite3").touch()

    try:
        main(["icu-patient-tracker", "--smoke-test", str(work_directory)])
    except RuntimeError as error:
        assert "prior smoke-test artifacts" in str(error)
    else:
        raise AssertionError("Smoke test unexpectedly reused an existing database.")


def test_release_smoke_rejects_ambiguous_arguments() -> None:
    assert main(["icu-patient-tracker", "--smoke-test"]) == 2
