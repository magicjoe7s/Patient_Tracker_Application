"""Round-trip the editable diagnostic checklist text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiagnosticTextEntry:
    title: str
    completed: bool
    result: str = ""


_CHECKBOX = re.compile(r"^\s*[-*+]?\s*\[([ xX])\]\s*(.+?)\s*$")


def parse_diagnostic_text(value: str) -> tuple[DiagnosticTextEntry, ...]:
    """Treat every nonblank line as one diagnostic record."""
    entries: list[DiagnosticTextEntry] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _CHECKBOX.match(line)
        checked = match is not None and match.group(1).casefold() == "x"
        content = match.group(2).strip() if match is not None else line.lstrip("-*+ ").strip()
        title, separator, result = content.partition(":")
        title = title.strip()
        result = result.strip() if separator else ""
        if title:
            entries.append(DiagnosticTextEntry(title, checked or bool(result), result))
    return tuple(entries)
