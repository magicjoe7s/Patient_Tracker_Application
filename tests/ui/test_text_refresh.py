"""Regression coverage for cursor-safe programmatic text refreshes."""

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QWidget

from icu_patient_tracker.ui.text_refresh import set_line_text_safely, set_plain_text_safely


def test_routine_refresh_does_not_replace_focused_multiline_draft() -> None:
    application = QApplication.instance() or QApplication(["icu-patient-tracker-test"])
    host = QWidget()
    editor = QPlainTextEdit(host)
    host.show()
    editor.show()
    editor.setPlainText("draft text")
    editor.setFocus()
    application.processEvents()
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)

    assert not set_plain_text_safely(editor, "persisted text")
    assert editor.toPlainText() == "draft text"
    assert editor.textCursor().selectedText() == "draft"
    host.close()


def test_routine_refresh_does_not_replace_focused_single_line_draft() -> None:
    application = QApplication.instance() or QApplication(["icu-patient-tracker-test"])
    host = QWidget()
    editor = QLineEdit(host)
    host.show()
    editor.show()
    editor.setText("draft text")
    editor.setFocus()
    application.processEvents()
    editor.setSelection(0, 5)

    assert not set_line_text_safely(editor, "persisted text")
    assert editor.text() == "draft text"
    assert editor.selectedText() == "draft"
    host.close()


def test_forced_context_refresh_replaces_text_and_keeps_cursor_in_bounds() -> None:
    application = QApplication.instance() or QApplication(["icu-patient-tracker-test"])
    host = QWidget()
    editor = QPlainTextEdit(host)
    host.show()
    editor.show()
    editor.setPlainText("long focused draft")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.setFocus()
    application.processEvents()

    assert set_plain_text_safely(editor, "new", force=True)
    assert editor.toPlainText() == "new"
    assert editor.textCursor().position() == len("new")
    host.close()
