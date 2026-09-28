"""Standard-library HTTP implementation of the desktop synchronization gateway."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from icu_patient_tracker.persistence.sync_repository import SyncOperation
from icu_patient_tracker.sync.contracts import ChangePage, PushResult, PushStatus, ServerChange


class SyncTransportError(RuntimeError):
    """The gateway could not be reached or returned an invalid response."""


class HttpSyncGateway:
    """Send version-one sync requests without adding a third-party HTTP dependency."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError("Sync base URL must start with http:// or https://.")
        if timeout_seconds <= 0:
            raise ValueError("Sync timeout must be greater than zero.")
        if token_provider is not None and not normalized_url.startswith("https://"):
            raise ValueError("Authenticated synchronization requires HTTPS.")
        self._base_url = normalized_url
        self._timeout_seconds = timeout_seconds
        self._token_provider = token_provider

    def health(self) -> dict[str, object]:
        return self._request("GET", "/health")

    def push(
        self,
        *,
        workspace_id: str,
        device_id: str,
        operations: tuple[SyncOperation, ...],
    ) -> tuple[PushResult, ...]:
        payload: dict[str, object] = {
            "workspace_id": workspace_id,
            "device_id": device_id,
            "operations": [
                {
                    "operation_id": str(operation.operation_id),
                    "entity_type": operation.entity_type,
                    "entity_id": str(operation.entity_id),
                    "operation": operation.operation,
                    "base_server_version": operation.base_server_version,
                    "payload": operation.payload,
                }
                for operation in operations
            ],
        }
        response = self._request("POST", "/v1/sync/push", payload)
        raw_results = _list(response, "results")
        return tuple(_push_result(item) for item in raw_results)

    def changes(
        self,
        *,
        workspace_id: str,
        after: int,
        limit: int = 100,
    ) -> ChangePage:
        query = urlencode({"workspace_id": workspace_id, "after": after, "limit": limit})
        response = self._request("GET", f"/v1/sync/changes?{query}")
        raw_changes = _list(response, "changes")
        next_cursor = _integer(response, "next_cursor")
        has_more = response.get("has_more")
        if not isinstance(has_more, bool):
            raise SyncTransportError("Gateway response field 'has_more' must be a boolean.")
        return ChangePage(
            changes=tuple(_server_change(item) for item in raw_changes),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        body = None
        headers = {"Accept": "application/json"}
        if self._token_provider is not None:
            token = self._token_provider()
            if not 32 <= len(token) <= 256 or any(character.isspace() for character in token):
                raise SyncTransportError("A valid device credential is required.")
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(f"{self._base_url}{path}", data=body, headers=headers, method=method)
        try:
            # Never forward a device credential through an HTTP redirect.
            opener = build_opener(_NoRedirect()).open if self._token_provider else urlopen
            with opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read(16_777_217)
                if len(raw) > 16_777_216:
                    raise SyncTransportError("Gateway response is too large.")
                raw_response = raw.decode("utf-8")
        except HTTPError as error:
            raise SyncTransportError(f"Gateway returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise SyncTransportError(f"Unable to reach sync gateway: {error}") from error
        try:
            decoded = json.loads(raw_response)
        except json.JSONDecodeError as error:
            raise SyncTransportError("Gateway returned invalid JSON.") from error
        if not isinstance(decoded, dict):
            raise SyncTransportError("Gateway response must be a JSON object.")
        return decoded


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _push_result(value: object) -> PushResult:
    item = _object(value)
    raw_status = _text(item, "status")
    if raw_status not in {"accepted", "conflict"}:
        raise SyncTransportError("Gateway returned an unknown push status.")
    status: PushStatus = "accepted" if raw_status == "accepted" else "conflict"
    raw_sequence = item.get("change_sequence")
    if raw_sequence is not None and (
        not isinstance(raw_sequence, int) or isinstance(raw_sequence, bool)
    ):
        raise SyncTransportError("Gateway change sequence must be an integer or null.")
    server_payload = _object(item.get("server_payload"))
    return PushResult(
        operation_id=_text(item, "operation_id"),
        status=status,
        entity_type=_text(item, "entity_type"),
        entity_id=_text(item, "entity_id"),
        server_version=_integer(item, "server_version"),
        change_sequence=raw_sequence,
        server_payload=server_payload,
    )


def _server_change(value: object) -> ServerChange:
    item = _object(value)
    return ServerChange(
        sequence=_integer(item, "sequence"),
        entity_type=_text(item, "entity_type"),
        entity_id=_text(item, "entity_id"),
        operation=_text(item, "operation"),
        server_version=_integer(item, "server_version"),
        payload=_object(item.get("payload")),
    )


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncTransportError("Gateway response contains a value that is not an object.")
    return value


def _list(value: dict[str, object], key: str) -> list[object]:
    result = value.get(key)
    if not isinstance(result, list):
        raise SyncTransportError(f"Gateway response field '{key}' must be an array.")
    return result


def _text(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise SyncTransportError(f"Gateway response field '{key}' must be text.")
    return result


def _integer(value: dict[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool):
        raise SyncTransportError(f"Gateway response field '{key}' must be an integer.")
    return result
