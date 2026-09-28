"""Numbered running-problem text parsing and rendering tests."""

from icu_patient_tracker.utils.problem_list_text import (
    ProblemListEntry,
    parse_problem_list,
    render_problem_list,
)


def test_numbered_problem_list_round_trips_nested_supporting_details() -> None:
    entries = (
        ProblemListEntry("Acute kidney injury", "Creatinine 3.2\nUrine output improving"),
        ProblemListEntry("Hypotension", "Improved after fluid bolus"),
    )

    rendered = render_problem_list(entries)

    assert rendered == (
        "1. Acute kidney injury\n"
        "   • Creatinine 3.2\n"
        "   • Urine output improving\n"
        "2. Hypotension\n"
        "   • Improved after fluid bolus"
    )
    assert parse_problem_list(rendered) == entries


def test_legacy_unnumbered_problem_lines_remain_compatible() -> None:
    assert parse_problem_list("- Anemia\nNew respiratory concern") == (
        ProblemListEntry("Anemia"),
        ProblemListEntry("New respiratory concern"),
    )
