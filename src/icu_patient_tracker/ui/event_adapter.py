"""Translate framework-independent application events into Qt signals."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from icu_patient_tracker.services.events import (
    ApplicationEvent,
    HospitalDayChanged,
    InProcessEventDispatcher,
    InstrumentationChanged,
    PatientChanged,
    PersistenceLifecycleEvent,
    ProblemChanged,
    SettingsChanged,
    SOAPChanged,
    TaskChanged,
)


class QtEventAdapter(QObject):
    """Own one deterministic subscription set and emit GUI-thread-safe signals."""

    patient_changed = Signal(str, str)
    day_changed = Signal(str, str)
    problem_changed = Signal(str, str)
    task_changed = Signal(str, str)
    instrumentation_changed = Signal(str, str)
    soap_changed = Signal(str, str)
    settings_changed = Signal(str)
    persistence_changed = Signal(str)
    any_changed = Signal(object)

    def __init__(self, dispatcher: InProcessEventDispatcher) -> None:
        super().__init__()
        self._disconnectors: list[Callable[[], None]] = []
        self._subscribe(dispatcher, PatientChanged, self.patient_changed.emit)
        self._subscribe(dispatcher, HospitalDayChanged, self.day_changed.emit)
        self._subscribe(dispatcher, ProblemChanged, self.problem_changed.emit)
        self._subscribe(dispatcher, TaskChanged, self.task_changed.emit)
        self._subscribe(dispatcher, InstrumentationChanged, self.instrumentation_changed.emit)
        self._subscribe(dispatcher, SOAPChanged, self.soap_changed.emit)
        self._disconnectors.append(dispatcher.subscribe(SettingsChanged, self._emit_settings))
        self._disconnectors.append(
            dispatcher.subscribe(PersistenceLifecycleEvent, self._emit_persistence)
        )

    def close(self) -> None:
        """Disconnect once so recreated presentation components do not duplicate updates."""
        for disconnect in self._disconnectors:
            disconnect()
        self._disconnectors.clear()

    def _subscribe(
        self,
        dispatcher: InProcessEventDispatcher,
        event_type: type[ApplicationEvent],
        emit_signal: Callable[[str, str], None],
    ) -> None:
        def emit(event: ApplicationEvent) -> None:
            emit_signal(event.aggregate_id, event.operation)
            self.any_changed.emit(event)

        self._disconnectors.append(dispatcher.subscribe(event_type, emit))

    def _emit_settings(self, event: ApplicationEvent) -> None:
        self.settings_changed.emit(event.operation)
        self.any_changed.emit(event)

    def _emit_persistence(self, event: ApplicationEvent) -> None:
        self.persistence_changed.emit(event.operation)
        # Dirty notifications are emitted for each editor change. They update the
        # small save indicator only; treating them as domain mutations used to run
        # analytics queries on every keystroke and caused visible input latency.
