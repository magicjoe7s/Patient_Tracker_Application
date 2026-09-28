"""Pure formatting helpers for Markdown-friendly Sandbox paste."""

from __future__ import annotations

import re


def format_sandbox_paste(text: str) -> str:
    """Normalize pasted plain text and recover common flattened Markdown boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    if "\n" in normalized:
        return normalized
    expanded = re.sub(r"\s*(---+|--+)\s*", r"\n\n\1\n\n", normalized)
    expanded = re.sub(r"\s+(#{2,6}\s+)", r"\n\n\1", expanded)
    expanded = re.sub(r"\s+((?:[-*]|\d+[.)]|\[[ xX]\])\s+)", r"\n\1", expanded)
    expanded = re.sub(r"\n{3,}", "\n\n", expanded)
    return expanded.strip("\n ")
