"""Static import-boundary checks for the presentation architecture."""

import ast
from pathlib import Path


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_and_services_do_not_import_qt() -> None:
    root = Path("src/icu_patient_tracker")
    for directory in (root / "domain", root / "services"):
        for path in directory.glob("*.py"):
            assert not any(module.startswith("PySide6") for module in imported_modules(path)), path


def test_presentation_does_not_import_persistence_or_repositories() -> None:
    root = Path("src/icu_patient_tracker")
    for directory in (root / "ui", root / "widgets", root / "dialogs"):
        for path in directory.glob("*.py"):
            modules = imported_modules(path)
            forbidden = {
                module
                for module in modules
                if module.startswith("sqlalchemy")
                or module.startswith("icu_patient_tracker.persistence")
                or module.startswith("icu_patient_tracker.repositories")
            }
            assert forbidden == set(), f"{path}: {sorted(forbidden)}"


def test_database_manager_consumers_are_composition_or_maintenance_roots() -> None:
    root = Path("src/icu_patient_tracker")
    consumers = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "icu_patient_tracker.persistence.database" in imported_modules(path):
            consumers.append(path.relative_to(root).as_posix())
    assert sorted(consumers) == [
        "app/bootstrap.py",
        "persistence/backup.py",
        "persistence/legacy_import.py",
    ]
