"""Pure action-registry parsing and generated-help tests."""

import pytest

from icu_patient_tracker.ui.action_registry import (
    DEFAULT_ACTIONS,
    ActionRegistry,
    CommandParseError,
    ParsedCommand,
)


def test_command_parser_resolves_aliases_arguments_and_whitespace() -> None:
    registry = ActionRegistry(DEFAULT_ACTIONS)

    assert registry.parse(" NP ") == ParsedCommand("new_patient")
    assert registry.parse("patient   Bella Rose") == ParsedCommand("select_patient", "bella rose")
    assert registry.parse("readmit ICU bella") == ParsedCommand("readmit", "bella")
    assert registry.parse("readmit") == ParsedCommand("readmit")
    assert registry.parse("hide completed") == ParsedCommand("hide_completed")
    assert registry.parse("focus physical") == ParsedCommand("focus", "physical")


def test_command_parser_reports_empty_incomplete_and_unknown_input() -> None:
    registry = ActionRegistry(DEFAULT_ACTIONS)

    with pytest.raises(CommandParseError, match="Enter a command"):
        registry.parse("   ")
    with pytest.raises(CommandParseError, match="requires"):
        registry.parse("status")
    with pytest.raises(CommandParseError, match="Unknown command"):
        registry.parse("teleport")


def test_generated_help_contains_every_registered_shortcut_and_command() -> None:
    registry = ActionRegistry(DEFAULT_ACTIONS)
    generated = registry.help_text()

    for definition in registry.definitions:
        for shortcut in definition.shortcuts:
            assert shortcut in generated
        if definition.commands:
            assert definition.command_usage in generated
            for alias in definition.commands[1:]:
                assert alias in generated

    native_editor_shortcuts = {"Ctrl+C", "Ctrl+X", "Ctrl+V", "Ctrl+A", "Ctrl+Z", "Ctrl+Y"}
    registered = {
        shortcut for definition in registry.definitions for shortcut in definition.shortcuts
    }
    assert registered.isdisjoint(native_editor_shortcuts)
