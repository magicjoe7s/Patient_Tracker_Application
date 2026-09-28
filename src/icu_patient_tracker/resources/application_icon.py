"""Application icon loading from packaged resources."""

from __future__ import annotations

import sys
from importlib.resources import files

from PySide6.QtGui import QIcon


def load_application_icon() -> QIcon:
    """Load the native or portable application icon for the current platform."""
    icon_name = "icu-patient-tracker.png" if sys.platform == "darwin" else "icu-patient-tracker.ico"
    icon_resource = files("icu_patient_tracker.resources").joinpath("icons", icon_name)
    return QIcon(str(icon_resource))
