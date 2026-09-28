"""Sync does not block startup or run network calls on the GUI thread."""

from threading import Event, get_ident

from PySide6.QtTest import QTest

from tests.ui.test_main_window import make_runtime


def test_unpaired_startup_never_starts_network_and_worker_returns_to_gui(tmp_path):
    runtime = make_runtime(tmp_path)
    release = Event()
    entered = Event()
    callbacks = []
    gui_thread = get_ident()
    adapter = runtime.sync
    try:
        assert adapter is not None
        adapter.tick()
        assert adapter.job is None
        assert adapter.auth is None

        def request():
            entered.set()
            release.wait(5)
            return get_ident()

        adapter._start_job(request, lambda worker: callbacks.append((worker, get_ident())))
        assert entered.wait(2)
        runtime.application.processEvents()
        assert callbacks == []
        release.set()
        for _ in range(100):
            QTest.qWait(10)
            if callbacks and adapter.job is None:
                break
        assert callbacks[0][0] != gui_thread
        assert callbacks[0][1] == gui_thread
        assert adapter.job is None
    finally:
        release.set()
        runtime.shutdown()
