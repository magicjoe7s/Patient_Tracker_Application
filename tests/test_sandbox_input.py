"""Sandbox paste-formatting tests."""

from icu_patient_tracker.utils.sandbox_input import format_sandbox_paste


def test_multiline_paste_normalizes_line_endings_tabs_and_trailing_space() -> None:
    assert format_sandbox_paste("## Plan\r\n\t- [ ] CBC   \r\n") == ("## Plan\n    - [ ] CBC\n")


def test_flattened_markdown_recovers_common_boundaries() -> None:
    pasted = "Scratch ## Tasks - [ ] CBC - [x] Fluids ## Notes #INPUT#"

    formatted = format_sandbox_paste(pasted)

    assert "\n\n## Tasks" in formatted
    assert "\n- [ ] CBC" in formatted
    assert "\n- [x] Fluids" in formatted
    assert "\n\n## Notes" in formatted
