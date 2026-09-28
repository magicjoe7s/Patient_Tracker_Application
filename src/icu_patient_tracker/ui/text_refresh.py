"""Cursor-safe updates for editable Qt text controls."""

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit


def set_plain_text_safely(
    editor: QPlainTextEdit,
    value: str,
    *,
    force: bool = False,
) -> bool:
    """Replace text only when necessary and never overwrite a focused draft routinely."""
    if editor.toPlainText() == value:
        return False
    if editor.hasFocus() and not force:
        return False
    cursor = editor.textCursor()
    anchor = cursor.anchor()
    position = cursor.position()
    vertical = editor.verticalScrollBar().value()
    horizontal = editor.horizontalScrollBar().value()
    editor.setPlainText(value)
    limit = len(value)
    restored = editor.textCursor()
    restored.setPosition(min(anchor, limit))
    restored.setPosition(min(position, limit), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(restored)
    editor.verticalScrollBar().setValue(vertical)
    editor.horizontalScrollBar().setValue(horizontal)
    return True


def set_line_text_safely(editor: QLineEdit, value: str, *, force: bool = False) -> bool:
    """Apply the same focused-draft rule to single-line editors."""
    if editor.text() == value:
        return False
    if editor.hasFocus() and not force:
        return False
    cursor_position = editor.cursorPosition()
    selection_start = editor.selectionStart()
    selection_length = len(editor.selectedText())
    editor.setText(value)
    limit = len(value)
    if selection_start >= 0:
        editor.setSelection(
            min(selection_start, limit),
            min(selection_length, max(0, limit - selection_start)),
        )
    else:
        editor.setCursorPosition(min(cursor_position, limit))
    return True
