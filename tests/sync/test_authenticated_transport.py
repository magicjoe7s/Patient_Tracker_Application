"""Production transport must not disclose a device token to an insecure endpoint."""

import pytest

from icu_patient_tracker.sync.http_gateway import HttpSyncGateway, SyncTransportError


def test_device_credential_requires_https():
    with pytest.raises(ValueError, match="requires HTTPS"):
        HttpSyncGateway("http://example.com", token_provider=lambda: "x" * 43)


def test_invalid_credential_is_rejected_before_network_access():
    gateway = HttpSyncGateway("https://example.invalid", token_provider=lambda: "")
    with pytest.raises(SyncTransportError, match="valid device credential"):
        gateway.health()
