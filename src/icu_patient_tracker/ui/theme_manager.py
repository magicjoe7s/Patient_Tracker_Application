"""Centralized application theme selection and application."""

from __future__ import annotations

from enum import StrEnum
from importlib.resources import files

from PySide6.QtWidgets import QApplication


class Theme(StrEnum):
    """Themes currently supplied by the application."""

    DARK = "dark"
    LIGHT = "light"


class ThemeManager:
    """Resolve and apply a selected application-wide stylesheet."""

    def apply(self, application: QApplication, theme_name: str) -> Theme:
        """Apply a packaged theme and return its validated identifier."""
        try:
            theme = Theme(theme_name.lower())
        except ValueError as error:
            raise ValueError(f"Unsupported theme: {theme_name}") from error

        stylesheet = (
            files("icu_patient_tracker.resources")
            .joinpath("themes", f"{theme.value}.qss")
            .read_text(encoding="utf-8")
        )
        application.setStyleSheet(stylesheet)
        return theme
