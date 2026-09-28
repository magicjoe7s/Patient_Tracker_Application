"""Save controls consistently support the optional Ctrl+S gesture."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from icu_patient_tracker.dialogs.problem_editor_dialog import ProblemEditorDialog


def test_ctrl_s_activates_dialog_save_button() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = ProblemEditorDialog()
    dialog.title.setText("Anemia")
    dialog.show()
    application.processEvents()

    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    application.processEvents()

    assert dialog.result() == QDialog.DialogCode.Accepted
