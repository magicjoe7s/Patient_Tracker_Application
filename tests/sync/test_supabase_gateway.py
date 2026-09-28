"""Check Supabase routing and credential boundaries without real credentials."""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from icu_patient_tracker.sync.http_gateway import SyncTransportError
from icu_patient_tracker.sync.supabase_gateway import SupabaseSyncGateway


def gateway(**overrides):
    return SupabaseSyncGateway(
        **{
            "project_url": "https://example.supabase.co",
            "publishable_key": "sb_publishable_test",
            "access_token_provider": lambda: "synthetic.jwt.token",
            "workspace_id": uuid4(),
            "device_id": uuid4(),
            **overrides,
        }
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.supabase.co",
        "https://example.supabase.co.evil.test",
        "https://secret@example.supabase.co",
        "https://example.supabase.co/?token=secret",
    ],
)
def test_rejects_unsafe_project_url(url):
    with pytest.raises(ValueError):
        gateway(project_url=url)


def test_rejects_server_secret_as_client_key():
    with pytest.raises(ValueError, match="publishable"):
        gateway(publishable_key="sb_secret_not-for-clients")


def test_pull_maps_rpc_and_auth_headers():
    workspace, device = uuid4(), uuid4()
    client = gateway(workspace_id=workspace, device_id=device)
    response = MagicMock()
    response.read.return_value = b'{"changes":[],"next_cursor":4,"has_more":false}'
    with patch("icu_patient_tracker.sync.supabase_gateway.build_opener") as opener:
        opener.return_value.open.return_value.__enter__.return_value = response
        result = client.changes(workspace_id=str(workspace), after=4)
        request = opener.return_value.open.call_args.args[0]
    assert result.next_cursor == 4
    assert request.full_url == "https://example.supabase.co/rest/v1/rpc/icu_sync_pull"
    assert request.get_header("Authorization") == "Bearer synthetic.jwt.token"
    assert request.get_header("Apikey") == "sb_publishable_test"
    assert json.loads(request.data) == {
        "p_workspace_id": str(workspace),
        "p_device_id": str(device),
        "p_after": 4,
        "p_limit": 100,
    }


def test_mismatched_workspace_never_sends_credentials():
    client = gateway()
    with patch("icu_patient_tracker.sync.supabase_gateway.build_opener") as opener:
        with pytest.raises(SyncTransportError, match="workspace"):
            client.changes(workspace_id=str(uuid4()), after=0)
        opener.assert_not_called()


def test_expired_login_message_does_not_echo_server_body():
    from urllib.error import HTTPError

    client = gateway()
    with patch("icu_patient_tracker.sync.supabase_gateway.build_opener") as opener:
        opener.return_value.open.side_effect = HTTPError(
            "https://example.supabase.co", 401, "", {}, None
        )
        with pytest.raises(SyncTransportError, match="authorization"):
            client.health()
