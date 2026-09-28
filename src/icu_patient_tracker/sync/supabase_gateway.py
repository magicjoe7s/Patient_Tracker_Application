"""Supabase hosted RPC adapter for the existing desktop sync coordinator."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener
from uuid import UUID

from icu_patient_tracker.sync.http_gateway import (
    HttpSyncGateway,
    SyncTransportError,
    _NoRedirect,
)


class SupabaseSyncGateway(HttpSyncGateway):
    """Use a publishable key and a signed-in user's short-lived access token.

    The token provider owns refresh and secure credential storage. Never pass a
    service-role key: server membership and device checks use the user's JWT.
    This adapter does not enable automatic clinical queuing or start UI networking.
    """

    def __init__(
        self,
        project_url: str,
        *,
        publishable_key: str,
        access_token_provider: Callable[[], str],
        workspace_id: UUID,
        device_id: UUID,
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urlsplit(project_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".supabase.co")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use the HTTPS Supabase project URL without a path or credentials.")
        if not publishable_key.startswith("sb_publishable_") or any(
            character.isspace() for character in publishable_key
        ):
            raise ValueError("Use a Supabase publishable key, not a secret or service-role key.")
        super().__init__(project_url, timeout_seconds=timeout_seconds)
        self._publishable_key = publishable_key
        self._access_token_provider = access_token_provider
        self._workspace_id = str(workspace_id)
        self._device_id = str(device_id)

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        if method == "GET" and path == "/health":
            self._rpc("icu_sync_pull", self._pull_arguments(0, 1))
            return {"status": "ok", "api_version": 1, "mode": "supabase"}
        if method == "POST" and path == "/v1/sync/push" and payload is not None:
            if (payload.get("workspace_id"), payload.get("device_id")) != (
                self._workspace_id,
                self._device_id,
            ):
                raise SyncTransportError("Sync request does not match this paired device.")
            return self._rpc("icu_sync_push", {"p_request": payload})
        if method == "GET" and path.startswith("/v1/sync/changes?"):
            query = parse_qs(urlsplit(path).query)
            if query.get("workspace_id") != [self._workspace_id]:
                raise SyncTransportError("Sync request does not match this workspace.")
            return self._rpc(
                "icu_sync_pull",
                self._pull_arguments(int(query["after"][0]), int(query["limit"][0])),
            )
        raise SyncTransportError("Unsupported Supabase sync request.")

    def _pull_arguments(self, after: int, limit: int) -> dict[str, object]:
        if after < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid sync cursor or page size.")
        return {
            "p_workspace_id": self._workspace_id,
            "p_device_id": self._device_id,
            "p_after": after,
            "p_limit": limit,
        }

    def _rpc(self, function: str, arguments: dict[str, object]) -> dict[str, object]:
        token = self._access_token_provider()
        if not token or len(token) > 16384 or any(c.isspace() for c in token):
            raise SyncTransportError("Sign in to the tracker before syncing.")
        body = json.dumps(arguments, allow_nan=False, separators=(",", ":")).encode()
        if len(body) > 1_048_576:
            raise SyncTransportError("Sync request exceeds the supported batch size.")
        request = Request(
            f"{self._base_url}/rest/v1/rpc/{function}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "apikey": self._publishable_key,
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with build_opener(_NoRedirect()).open(
                request, timeout=self._timeout_seconds
            ) as response:
                raw = response.read(16_777_217)
        except HTTPError as error:
            if error.code in (401, 403):
                raise SyncTransportError(
                    "Tracker login or device authorization is required."
                ) from error
            raise SyncTransportError(f"Supabase sync returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise SyncTransportError(
                "Supabase sync is unavailable; local changes remain queued."
            ) from error
        if len(raw) > 16_777_216:
            raise SyncTransportError("Supabase sync response is too large.")
        try:
            decoded = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise SyncTransportError("Supabase returned an invalid sync response.") from error
        if not isinstance(decoded, dict):
            raise SyncTransportError("Supabase returned an invalid sync response.")
        return decoded
