"""Application event subscription lifetime tests."""

from icu_patient_tracker.services.events import InProcessEventDispatcher, PatientChanged


def test_event_subscription_disconnect_is_idempotent() -> None:
    dispatcher = InProcessEventDispatcher()
    received: list[PatientChanged] = []
    disconnect = dispatcher.subscribe(PatientChanged, received.append)

    dispatcher.publish(PatientChanged("A1", "created"))
    disconnect()
    disconnect()
    dispatcher.publish(PatientChanged("A1", "updated"))

    assert [event.operation for event in received] == ["created"]
