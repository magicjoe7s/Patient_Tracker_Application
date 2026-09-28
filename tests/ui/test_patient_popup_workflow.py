"""Shared-context Patient Popup handoff and navigation tests."""

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QShortcut, QTextCursor

from icu_patient_tracker.app.bootstrap import ApplicationRuntime, create_runtime
from icu_patient_tracker.app.config import AppConfig, ConfigManager


def _runtime(tmp_path: Path) -> ApplicationRuntime:
    config_path = tmp_path / "config.json"
    ConfigManager(config_path).save(
        AppConfig(
            database_path=tmp_path / "tracker.sqlite3",
            backup_directory=tmp_path / "backups",
            autosave_debounce_seconds=0,
        )
    )
    return create_runtime(["icu-patient-tracker"], config_path)


def test_popup_handoff_saves_main_and_returns_popup_edits(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn=None,
            name="Bella",
            species="Canine",
        )
        main_editor = runtime.window.workspace.soap.markdown
        main_editor.setPlainText("Main handoff #INPUT#")
        runtime.window.show()

        runtime.window._show_patient_popup("soap")
        popup = runtime.window._patient_popup

        assert popup is not None and popup.isVisible()
        assert not runtime.window.isVisible()
        assert popup.soap_editor.toPlainText() == "Main handoff #INPUT#"
        popup.soap_editor.setPlainText("Popup canonical text")
        cursor = popup.soap_editor.textCursor()
        cursor.setPosition(3)
        cursor.setPosition(8, cursor.MoveMode.KeepAnchor)
        popup.soap_editor.setTextCursor(cursor)
        popup.set_mode("sandbox")
        popup.set_mode("soap")
        assert popup.soap_editor.textCursor().selectionStart() == 3
        assert popup.soap_editor.textCursor().selectionEnd() == 8

        assert popup.return_to_main()

        assert runtime.window.isVisible()
        assert not popup.isVisible()
        assert main_editor.toPlainText() == "Popup canonical text"
        day = runtime.controller.selected_day()
        assert day is not None
        assert day.soap_documents[-1].markdown_text == "Popup canonical text"
    finally:
        runtime.shutdown()


def test_popup_patient_navigation_flushes_and_restores_context_caret(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        patients = runtime.controller.services.patients
        first = patients.create(name="First", species="Canine")
        second = patients.create(name="Second", species="Feline")
        assert runtime.controller.select_patient(first.id)
        runtime.window._show_patient_popup("sandbox")
        popup = runtime.window._patient_popup
        assert popup is not None
        popup.sandbox_editor.setPlainText("first sandbox")
        cursor = popup.sandbox_editor.textCursor()
        cursor.setPosition(2)
        popup.sandbox_editor.setTextCursor(cursor)

        assert popup.select_relative_patient(1)
        assert runtime.controller.context.patient_id == second.id
        assert patients.get(first.id).hospital_days[-1].sandbox_text == "first sandbox"
        popup.sandbox_editor.setPlainText("second sandbox")
        cursor = popup.sandbox_editor.textCursor()
        cursor.setPosition(6)
        popup.sandbox_editor.setTextCursor(cursor)

        assert popup.select_relative_patient(-1)
        assert runtime.controller.context.patient_id == first.id
        assert popup.sandbox_editor.toPlainText() == "first sandbox"
        assert popup.sandbox_editor.textCursor().position() == 2
        assert patients.get(second.id).hospital_days[-1].sandbox_text == "second sandbox"
    finally:
        runtime.shutdown()


def test_popup_autosave_preserves_the_active_cursor_and_selection(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn=None,
            name="Bella",
            species="Canine",
        )
        runtime.window._show_patient_popup("soap")
        popup = runtime.window._patient_popup
        assert popup is not None
        draft = "Popup typing remains uninterrupted"
        popup.soap_editor.setPlainText(draft)
        popup.soap_editor.setFocus()
        cursor = popup.soap_editor.textCursor()
        cursor.setPosition(6)
        cursor.setPosition(12, QTextCursor.MoveMode.KeepAnchor)
        popup.soap_editor.setTextCursor(cursor)

        assert runtime.controller.flush_pending()
        runtime.application.processEvents()

        saved_cursor = popup.soap_editor.textCursor()
        assert popup.soap_editor.hasFocus()
        assert popup.soap_editor.toPlainText() == draft
        assert saved_cursor.selectionStart() == 6
        assert saved_cursor.selectionEnd() == 12
    finally:
        runtime.shutdown()


def test_popup_compact_pin_and_failed_save_safety(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn=None,
            name="Bella",
            species="Canine",
        )
        runtime.window.show()
        runtime.window._show_patient_popup("soap")
        popup = runtime.window._patient_popup
        assert popup is not None

        popup.set_compact(True)
        assert popup.is_compact
        assert popup.size().toTuple() == popup.COMPACT_SIZE
        assert not popup.editors.isVisible()
        assert not popup.main_button.isVisible()
        assert popup.compact_button.text() == "Full"

        start = popup.frameGeometry().topLeft()
        press_global = start + popup.patient_label.geometry().center()
        move_global = press_global + popup.patient_label.geometry().bottomRight()
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(4, 4),
            QPointF(press_global),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(20, 20),
            QPointF(move_global),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert popup.eventFilter(popup.patient_label, press)
        assert popup.eventFilter(popup.patient_label, move)
        assert popup.frameGeometry().topLeft() != start

        popup.set_compact(False)
        assert popup.editors.isVisible()
        popup.pin.setChecked(False)
        assert not popup.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

        popup.soap_editor.setPlainText("must not be discarded")
        original_flush = runtime.controller.flush_pending
        monkeypatch.setattr(runtime.controller, "flush_pending", lambda: False)
        assert not popup.return_to_main()
        assert popup.isVisible()
        assert not runtime.window.isVisible()
        monkeypatch.setattr(runtime.controller, "flush_pending", original_flush)
    finally:
        runtime.shutdown()


def test_small_visible_workspace_hands_off_to_popup(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn=None,
            name="Bella",
            species="Canine",
        )
        runtime.window.show()
        runtime.window.resize(800, 550)
        runtime.application.processEvents()
        runtime.application.processEvents()

        popup = runtime.window._patient_popup
        assert popup is not None and popup.isVisible()
        assert not runtime.window.isVisible()
        assert popup.return_to_main()
    finally:
        runtime.shutdown()


def test_patient_popup_exposes_primary_save_new_and_find_shortcuts(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.window.patient_panel.create_patient(
            mrn="123456",
            name="Bella",
            species="Canine",
        )
        runtime.window._show_patient_popup("sandbox")
        popup = runtime.window._patient_popup
        assert popup is not None
        sequences = {
            shortcut.key().toString()
            for shortcut in popup.findChildren(QShortcut)
        }
        assert {"Ctrl+S", "Ctrl+N", "Ctrl+F"} <= sequences

        popup.sandbox_editor.setPlainText("Saved from popup shortcut")
        popup.save_requested.emit()
        assert popup.status_label.text() == "Saved"
        assert runtime.controller.selected_day().sandbox_text == "Saved from popup shortcut"
    finally:
        runtime.shutdown()
