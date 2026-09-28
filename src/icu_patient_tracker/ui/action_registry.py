"""Framework-independent action metadata and typed command parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ArgumentMode = Literal["none", "required", "optional"]


class CommandParseError(ValueError):
    """A typed command is empty, incomplete, or unknown."""


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """One source of truth for an action's UI and command surfaces."""

    name: str
    label: str
    description: str
    menu: str | None = None
    toolbar: bool = False
    shortcuts: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    argument_mode: ArgumentMode = "none"
    argument_label: str = ""

    @property
    def command_usage(self) -> str:
        if not self.commands:
            return ""
        base = self.commands[0]
        if self.argument_mode == "required":
            return f"{base} <{self.argument_label}>"
        if self.argument_mode == "optional":
            return f"{base} [<{self.argument_label}>]"
        return base


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Resolved action name plus its normalized optional argument."""

    action_name: str
    argument: str | None = None


class ActionRegistry:
    """Validate definitions, resolve commands, and generate drift-free help."""

    def __init__(self, definitions: tuple[ActionDefinition, ...]) -> None:
        self.definitions = definitions
        self._by_name: dict[str, ActionDefinition] = {}
        self._commands: dict[str, ActionDefinition] = {}
        shortcuts: dict[str, str] = {}
        for definition in definitions:
            if definition.name in self._by_name:
                raise ValueError(f"Duplicate action name: {definition.name}")
            self._by_name[definition.name] = definition
            for command in definition.commands:
                normalized = self.normalize(command)
                if normalized in self._commands:
                    raise ValueError(f"Duplicate command alias: {command}")
                self._commands[normalized] = definition
            for shortcut in definition.shortcuts:
                normalized_shortcut = shortcut.casefold()
                if normalized_shortcut in shortcuts:
                    raise ValueError(
                        f"Duplicate shortcut {shortcut}: {shortcuts[normalized_shortcut]} and "
                        f"{definition.name}"
                    )
                shortcuts[normalized_shortcut] = definition.name

    def definition(self, name: str) -> ActionDefinition:
        return self._by_name[name]

    def parse(self, raw: str) -> ParsedCommand:
        command = self.normalize(raw)
        if not command:
            raise CommandParseError("Enter a command.")
        exact = self._commands.get(command)
        if exact is not None:
            if exact.argument_mode == "required":
                raise CommandParseError(f"{exact.commands[0]} requires <{exact.argument_label}>.")
            return ParsedCommand(exact.name)
        aliases = sorted(self._commands, key=len, reverse=True)
        for alias in aliases:
            definition = self._commands[alias]
            prefix = f"{alias} "
            if definition.argument_mode == "none" or not command.startswith(prefix):
                continue
            argument = command[len(prefix) :].strip()
            if argument:
                return ParsedCommand(definition.name, argument)
        raise CommandParseError(f"Unknown command: {raw.strip()}. Use help for available commands.")

    def help_text(self) -> str:
        lines = ["ICU Patient Tracker — Commands and Shortcuts", "", "Keyboard shortcuts"]
        shortcut_definitions = tuple(
            definition for definition in self.definitions if definition.shortcuts
        )
        for definition in shortcut_definitions:
            lines.append(
                f"- {' / '.join(definition.shortcuts)} — {definition.label}: "
                f"{definition.description}"
            )
        lines.extend(("", "Typed commands"))
        for definition in self.definitions:
            if not definition.commands:
                continue
            aliases = ", ".join(definition.commands[1:])
            suffix = f" (aliases: {aliases})" if aliases else ""
            lines.append(f"- {definition.command_usage}{suffix} — {definition.description}")
        lines.extend(
            (
                "",
                "Text editing",
                "- Standard copy, cut, paste, select-all, undo, redo, and word-editing "
                "shortcuts remain native to focused editors.",
            )
        )
        return "\n".join(lines)

    @staticmethod
    def normalize(value: str) -> str:
        return " ".join(value.strip().casefold().split())


DEFAULT_ACTIONS = (
    ActionDefinition(
        "new_patient",
        "New Patient",
        "Create a patient.",
        "File",
        True,
        ("Ctrl+N",),
        ("np", "new patient"),
    ),
    ActionDefinition(
        "new_day",
        "New Hospital Day",
        "Add a hospital day.",
        "File",
        True,
        ("Ctrl+Shift+D", "Alt+N"),
        ("nd", "new day"),
    ),
    ActionDefinition(
        "save",
        "Save Now",
        "Flush all pending editors.",
        "File",
        True,
        ("Ctrl+S",),
        ("save",),
    ),
    ActionDefinition(
        "create_backup",
        "Create Backup",
        "Create and verify a database snapshot.",
        "File",
        False,
        ("Ctrl+Shift+B",),
        ("backup", "create backup"),
    ),
    ActionDefinition(
        "restore_backup",
        "Restore Backup",
        "Review and restore a verified database snapshot.",
        "File",
        False,
        (),
        ("restore backup",),
    ),
    ActionDefinition("exit", "Exit", "Close safely.", "File", False, ("Ctrl+Q",)),
    ActionDefinition(
        "find",
        "Find Patient",
        "Focus live patient search.",
        "Navigate",
        True,
        ("Ctrl+F",),
        ("focus search",),
    ),
    ActionDefinition(
        "previous_patient",
        "Previous Patient",
        "Select the previous active patient.",
        "Navigate",
        False,
        ("Ctrl+Shift+J",),
        ("prev", "previous"),
    ),
    ActionDefinition(
        "next_patient",
        "Next Patient",
        "Select the next active patient.",
        "Navigate",
        False,
        ("Ctrl+Shift+L",),
        ("next",),
    ),
    ActionDefinition(
        "previous_day",
        "Previous Day",
        "Select the previous hospital day.",
        "Navigate",
        False,
        ("Ctrl+Shift+I",),
    ),
    ActionDefinition(
        "next_day",
        "Next Day",
        "Select the next hospital day.",
        "Navigate",
        False,
        ("Ctrl+Shift+K",),
    ),
    ActionDefinition(
        "rename_patient",
        "Rename Patient",
        "Rename the selected patient.",
        "Navigate",
        False,
        ("F2",),
    ),
    ActionDefinition(
        "new_todo",
        "New To Do",
        "Add a selected-day To Do.",
        "Tools",
        False,
        ("Ctrl+T",),
        ("todo", "new todo"),
    ),
    ActionDefinition(
        "new_diagnostic",
        "New Pending Diagnostic",
        "Add a selected-day diagnostic.",
        "Tools",
        False,
        ("Ctrl+D",),
    ),
    ActionDefinition(
        "patient_popup",
        "Patient Popup",
        "Open the SOAP popup.",
        "Tools",
        True,
        ("Ctrl+P",),
        ("popup", "soap popup"),
    ),
    ActionDefinition(
        "sandbox_popup",
        "Sandbox Popup",
        "Open the Sandbox popup.",
        "Tools",
        False,
        (),
        ("sandbox popup", "popup sandbox"),
    ),
    ActionDefinition(
        "toggle_soap",
        "Toggle SOAP Workspace",
        "Toggle SOAP and charting tabs.",
        "Tools",
        False,
        ("Alt+S",),
        ("soap", "toggle soap"),
    ),
    ActionDefinition(
        "task_board",
        "Task Board",
        "Open the consolidated task board.",
        "Tools",
        True,
        ("Ctrl+Alt+T", "Ctrl+Shift+T"),
        ("tasks", "task board", "board"),
    ),
    ActionDefinition(
        "pending_diagnostics",
        "Pending Diagnostics",
        "Open selected-day diagnostics.",
        "Tools",
        False,
        ("Ctrl+Shift+P",),
    ),
    ActionDefinition(
        "hide_completed",
        "Hide Completed",
        "Hide completed tasks on every task surface.",
        "Tools",
        False,
        ("Ctrl+Alt+H",),
        ("hide done", "hide completed"),
    ),
    ActionDefinition(
        "show_completed",
        "Show Completed",
        "Show completed tasks on every task surface.",
        "Tools",
        False,
        (),
        ("show done", "show completed"),
    ),
    ActionDefinition(
        "toggle_pin",
        "Toggle Main Window Pin",
        "Toggle always-on-top for the main window.",
        "View",
        False,
        ("Ctrl+Alt+P",),
        ("pin", "toggle pin"),
    ),
    ActionDefinition(
        "toggle_sidebar",
        "Toggle Patient Sidebar",
        "Collapse or restore the patient sidebar.",
        "View",
        False,
        ("Ctrl+Alt+L",),
    ),
    ActionDefinition(
        "resize_small",
        "Small Window",
        "Use the small window preset.",
        "View",
        False,
        ("Ctrl+Alt+1",),
    ),
    ActionDefinition(
        "resize_medium",
        "Medium Window",
        "Use the medium window preset.",
        "View",
        False,
        ("Ctrl+Alt+2",),
    ),
    ActionDefinition(
        "resize_large",
        "Large Window",
        "Use the large window preset.",
        "View",
        False,
        ("Ctrl+Alt+3",),
    ),
    ActionDefinition(
        "resize_fit", "Fit Monitor", "Fit the active monitor.", "View", False, ("Ctrl+Alt+0",)
    ),
    ActionDefinition(
        "copy_soap",
        "Copy SOAP",
        "Copy canonical SOAP and mark the day uploaded.",
        "Tools",
        False,
        (),
        ("copy", "copy soap"),
    ),
    ActionDefinition(
        "analytics",
        "Analytics",
        "Open the derived operational analytics report.",
        "Tools",
        True,
        ("Ctrl+Alt+A",),
        ("analytics", "report"),
    ),
    ActionDefinition(
        "settings", "Settings", "Open device-local settings.", "Tools", False, ("Ctrl+,",)
    ),
    ActionDefinition(
        "command_palette",
        "Command Palette",
        "Run a typed workflow command.",
        "Tools",
        True,
        ("Ctrl+K",),
    ),
    ActionDefinition(
        "help",
        "Help / Shortcuts",
        "Show generated command help.",
        "Help",
        False,
        ("F1",),
        ("help", "h", "?"),
    ),
    ActionDefinition(
        "select_patient",
        "Select Patient",
        "Select the best active patient match.",
        commands=("p", "patient"),
        argument_mode="required",
        argument_label="patient query",
    ),
    ActionDefinition(
        "select_day",
        "Select Day",
        "Select a day by date or label.",
        commands=("day",),
        argument_mode="required",
        argument_label="date or label",
    ),
    ActionDefinition(
        "readmit",
        "Readmit Patient",
        "Readmit a Home or IMC patient.",
        commands=("readmit", "readmit icu"),
        argument_mode="optional",
        argument_label="patient query",
    ),
    ActionDefinition(
        "set_status",
        "Set Patient Status",
        "Change the selected disposition.",
        commands=("status",),
        argument_mode="required",
        argument_label="status",
    ),
    ActionDefinition(
        "focus",
        "Focus Workflow",
        "Focus a named clinical surface.",
        commands=("focus",),
        argument_mode="required",
        argument_label="target",
    ),
    ActionDefinition(
        "focus_problem", "Focus Problem List", "Focus the problem list.", shortcuts=("Alt+P",)
    ),
    ActionDefinition(
        "focus_exam", "Focus Examination", "Focus physical examination.", shortcuts=("Alt+E",)
    ),
    ActionDefinition(
        "focus_treatment", "Focus Treatment", "Focus treatment changes.", shortcuts=("Alt+T",)
    ),
)
