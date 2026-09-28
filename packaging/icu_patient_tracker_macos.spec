# PyInstaller configuration for the native macOS application bundle.

import os
from importlib.metadata import version
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH).parent
source_root = project_root / "src"
icon_path = Path(os.environ["ICU_MACOS_ICON"])

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
    *collect_submodules("keyring.backends"),
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
    excludes=["psycopg", "psycopg_binary", "psycopg_pool"],
    noarchive=False,
    optimize=0,
)
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collected = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ICU Patient Tracker",
)

application = BUNDLE(
    collected,
    name="ICU Patient Tracker.app",
    icon=str(icon_path),
    bundle_identifier="com.icupatienttracker.desktop",
    version=version("icu-patient-tracker"),
    info_plist={
        "CFBundleDisplayName": "ICU Patient Tracker",
        "CFBundleName": "ICU Patient Tracker",
        "CFBundleShortVersionString": version("icu-patient-tracker"),
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    },
)
