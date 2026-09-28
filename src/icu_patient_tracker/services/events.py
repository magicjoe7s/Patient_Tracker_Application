"""Typed, in-process events published only after successful commits."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    """A metadata-only notification; clinical free text is intentionally excluded."""

    aggregate_id: str
    operation: str
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class PatientChanged(ApplicationEvent):
    """A patient aggregate changed."""


@dataclass(frozen=True, slots=True)
class HospitalDayChanged(ApplicationEvent):
    """A hospital-day aggregate changed."""


@dataclass(frozen=True, slots=True)
class TaskChanged(ApplicationEvent):
    """A task occurrence or lineage changed."""


@dataclass(frozen=True, slots=True)
class SOAPChanged(ApplicationEvent):
    """A SOAP document changed."""


@dataclass(frozen=True, slots=True)
class ReminderChanged(ApplicationEvent):
    """A reminder specification or state changed."""


@dataclass(frozen=True, slots=True)
class ProblemChanged(ApplicationEvent):
    """A problem-list member or ordering changed."""


@dataclass(frozen=True, slots=True)
class InstrumentationChanged(ApplicationEvent):
    """A device record or clinical state changed."""


@dataclass(frozen=True, slots=True)
class SettingsChanged(ApplicationEvent):
    """Device-local settings changed."""


@dataclass(frozen=True, slots=True)
class PersistenceLifecycleEvent(ApplicationEvent):
    """Autosave, backup, or restore state changed."""


EventHandler = Callable[[ApplicationEvent], None]


class EventPublisher(Protocol):
    """Publish committed application events."""

    def publish(self, event: ApplicationEvent) -> None: ...


class NullEventPublisher:
    """Default publisher for consumers that do not need notifications."""

    def publish(self, event: ApplicationEvent) -> None:
        del event


class InProcessEventDispatcher:
    """Synchronously dispatch events by type without infrastructure coupling."""

    def __init__(self) -> None:
        self._handlers: defaultdict[type[ApplicationEvent], list[EventHandler]] = defaultdict(list)

    def subscribe(
        self, event_type: type[ApplicationEvent], handler: EventHandler
    ) -> Callable[[], None]:
        self._handlers[event_type].append(handler)

        disconnected = False

        def disconnect() -> None:
            nonlocal disconnected
            if disconnected:
                return
            disconnected = True
            handlers = self._handlers[event_type]
            if handler in handlers:
                handlers.remove(handler)

        return disconnect

    def publish(self, event: ApplicationEvent) -> None:
        for registered_type, handlers in tuple(self._handlers.items()):
            if isinstance(event, registered_type):
                for handler in tuple(handlers):
                    handler(event)


class RecordingEventPublisher:
    """Small deterministic publisher useful to composition roots and tests."""

    def __init__(self) -> None:
        self.events: list[ApplicationEvent] = []

    def publish(self, event: ApplicationEvent) -> None:
        self.events.append(event)
