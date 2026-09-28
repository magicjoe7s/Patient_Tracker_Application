"""Session renewal never persists the password or accepts another account."""

import json
from unittest.mock import MagicMock, patch

import pytest

from icu_patient_tracker.sync.supabase_auth import SignInRequired, SupabaseAuth


def test_signin_refresh_and_local_signout():
    store = MagicMock()
    auth = SupabaseAuth("https://example.supabase.co", "public-key", "owner", store)
    response = MagicMock()
    response.read.return_value = json.dumps(
        {
            "user": {"id": "owner"},
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
    ).encode()
    with patch("icu_patient_tracker.sync.supabase_auth.build_opener") as opener:
        opener.return_value.open.return_value.__enter__.return_value = response
        auth.sign_in("test@example.test", "test-password")
        store.write.assert_called_once_with("refresh")
        assert auth.access_token() == "access"
        assert opener.return_value.open.call_count == 1
        auth._expires_at = 0
        store.read.return_value = "refresh"
        assert auth.access_token() == "access"
        request = opener.return_value.open.call_args.args[0]
        assert json.loads(request.data) == {"refresh_token": "refresh"}
    auth.sign_out()
    store.delete.assert_called_once()
    assert auth._access == ""


def test_wrong_owner_is_not_remembered():
    store = MagicMock()
    auth = SupabaseAuth("https://example.supabase.co", "public-key", "owner", store)
    response = MagicMock()
    response.read.return_value = b'{"user":{"id":"someone-else"}}'
    with patch("icu_patient_tracker.sync.supabase_auth.build_opener") as opener:
        opener.return_value.open.return_value.__enter__.return_value = response
        with pytest.raises(SignInRequired):
            auth.sign_in("test@example.test", "test-password")
    store.write.assert_not_called()
