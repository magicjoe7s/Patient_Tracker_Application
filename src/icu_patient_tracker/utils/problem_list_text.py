"""Parse and render the compact numbered running-problem editor."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProblemListEntry:
    """One problem title and its freeform supporting-detail lines."""

    title: str
    description: str = ""


_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_TOP_LEVEL_BULLET = re.compile(r"^[-*•]\s+(.+?)\s*$")
_NESTED_BULLET = re.compile(r"^\s+[-*•]\s+(.+?)\s*$")


def render_problem_list(entries: tuple[ProblemListEntry, ...]) -> str:
    """Render stable numbering with indented bullets derived from stored order."""
    lines: list[str] = []
    for number, entry in enumerate(entries, 1):
        lines.append(f"{number}. {entry.title.strip()}")
        lines.extend(
            f"   • {detail.strip()}" for detail in entry.description.splitlines() if detail.strip()
        )
    return "\n".join(lines)


def parse_problem_list(text: str) -> tuple[ProblemListEntry, ...]:
    """Parse numbered text while accepting the former top-level bullet format."""
    entries: list[ProblemListEntry] = []
    details: list[str] = []

    def finish() -> None:
        nonlocal details
        if entries and details:
            current = entries[-1]
            entries[-1] = ProblemListEntry(current.title, "\n".join(details))
        details = []

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        numbered = _NUMBERED.match(raw_line)
        legacy = _TOP_LEVEL_BULLET.match(raw_line)
        nested = _NESTED_BULLET.match(raw_line)
        if numbered or legacy:
            finish()
            title = (numbered or legacy).group(1).strip()  # type: ignore[union-attr]
            if title:
                entries.append(ProblemListEntry(title))
        elif nested and entries:
            details.append(nested.group(1).strip())
        else:
            finish()
            entries.append(ProblemListEntry(raw_line.strip()))
    finish()
    return tuple(entry for entry in entries if entry.title)
