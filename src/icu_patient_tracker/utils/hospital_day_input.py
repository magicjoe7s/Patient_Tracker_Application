"""Strict parsing for the hospital-day date and optional note syntax."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ParsedHospitalDayInput:
    """Validated calendar date and optional display note."""

    calendar_date: date
    label: str | None


def parse_hospital_day_input(value: str) -> ParsedHospitalDayInput:
    """Parse `YYYY-MM-DD`, optionally followed by `| note`."""
    date_text, separator, note = value.strip().partition("|")
    normalized_date = date_text.strip()
    try:
        calendar_date = date.fromisoformat(normalized_date)
    except ValueError as error:
        raise ValueError("Enter the date as YYYY-MM-DD, optionally followed by | note.") from error
    if normalized_date != calendar_date.isoformat():
        raise ValueError("Enter the date as YYYY-MM-DD, optionally followed by | note.")
    label = note.strip() if separator else ""
    return ParsedHospitalDayInput(calendar_date, label or None)
