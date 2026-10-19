"""Release test windows between cases while retaining the shared QApplication."""

import gc
from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def release_test_windows() -> Iterator[None]:
    yield
    application = QApplication.instance()
    if application is None:
        return
    # Runtime shutdown closes resident windows but does not destroy their Qt
    # objects. Retaining dozens per case makes subsequent global theme updates
    # progressively slower and leaks state between otherwise isolated tests.
    for window in QApplication.topLevelWidgets():
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
