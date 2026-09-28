"""Synchronization page validation tests."""

from uuid import uuid4

import pytest

from icu_patient_tracker.sync.contracts import ServerChange
from icu_patient_tracker.sync.validation import validate_change_page


def change(sequence: int) -> ServerChange:
    return ServerChange(sequence, "patient", str(uuid4()), "upsert", 1, {})


def test_accepts_ordered_page_and_matching_cursor() -> None:
    validate_change_page(4, (change(5), change(6)), 6, False)


@pytest.mark.parametrize(
    ("changes", "next_cursor", "has_more"),
    [
        ((change(4),), 4, False),
        ((change(6), change(5)), 5, False),
        ((change(5),), 6, False),
        ((), 4, True),
    ],
)
def test_rejects_invalid_change_pages(
    changes: tuple[ServerChange, ...], next_cursor: int, has_more: bool
) -> None:
    with pytest.raises(RuntimeError):
        validate_change_page(4, changes, next_cursor, has_more)
