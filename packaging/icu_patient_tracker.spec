# PyInstaller configuration for the Windows one-directory release.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH).parent
source_root = project_root / "src"

datas = [
    *collect_data_files("icu_patient_tracker.resources"),
    *collect_data_files(
        "icu_patient_tracker.persistence.migrations",
        include_py_files=True,
    ),
]
hidden_imports = [
    "icu_patient_tracker.persistence.migrations.env",
    "logging.config",
    "sqlalchemy.dialects.sqlite",
    *collect_submodules("icu_patient_tracker.persistence.migrations.versions"),
]

analysis = Analysis(
    [str(source_root / "icu_patient_tracker" / "main.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # SQLAlchemy's generic PyInstaller hook discovers optional drivers installed on
    # the build machine. Production sync uses HTTPS/Supabase, so do not ship the
    # retired direct-PostgreSQL client stack in the desktop bundle.
    excludes=[
        "psycopg",
        "psycopg_binary",
        "psycopg_pool",
    ],
    noarchive=False,
    optimize=0,
)
# Qt on Windows uses the operating system's unversioned ICU API. An unrelated
# icuuc.dll on the build machine's PATH (for example Poppler's) can shadow it and
# make QtWidgets fail to import in the packaged app.
if os.name == "nt":
    analysis.binaries = [
        entry for entry in analysis.binaries if Path(entry[0]).name.lower() != "icuuc.dll"
    ]
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ICU Patient Tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    icon=str(source_root / "icu_patient_tracker" / "resources" / "icons" / "icu-patient-tracker.ico"),
    console=os.environ.get("ICU_BUILD_CONSOLE") == "1",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ICU Patient Tracker",
)
