"""Validation shared by synchronization coordinators."""

from __future__ import annotations

from icu_patient_tracker.sync.contracts import ServerChange


def validate_change_page(
    cursor: int,
    changes: tuple[ServerChange, ...],
    next_cursor: int,
    has_more: bool,
) -> None:
    """Reject invalid or non-progressing remote change pages."""
    sequences = [change.sequence for change in changes]
    if any(sequence <= cursor for sequence in sequences):
        raise RuntimeError("Gateway returned a change at or before the requested cursor.")
    if sequences != sorted(set(sequences)):
        raise RuntimeError("Gateway returned duplicate or unordered change sequences.")
    expected_cursor = sequences[-1] if sequences else cursor
    if next_cursor != expected_cursor:
        raise RuntimeError("Gateway returned a cursor that does not match its change page.")
    if has_more and not changes:
        raise RuntimeError("Gateway returned an empty page while claiming more changes exist.")
