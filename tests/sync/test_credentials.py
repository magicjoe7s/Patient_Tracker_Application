"""Cross-platform secure refresh-token storage tests."""

import pytest

from icu_patient_tracker.sync.credentials import MacOSTokenStore, create_token_store


class _MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, token: str) -> None:
        self.values[(service, account)] = token

    def delete_password(self, service: str, account: str) -> None:
        del self.values[(service, account)]


def test_macos_token_store_round_trips_without_storing_plaintext_files() -> None:
    backend = _MemoryKeyring()
    store = MacOSTokenStore("workspace/device", backend)

    assert store.read() is None
    store.write("refresh-token-value")
    assert store.read() == "refresh-token-value"
    store.delete()
    assert store.read() is None
    store.delete()


def test_token_store_factory_rejects_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr("icu_patient_tracker.sync.credentials.sys.platform", "linux")
    with pytest.raises(RuntimeError, match="Windows and macOS"):
        create_token_store("workspace/device")
