"""Supabase user sessions with private refresh-token persistence."""

from __future__ import annotations

import json
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from icu_patient_tracker.sync.http_gateway import _NoRedirect


class TokenStore(Protocol):
    def read(self) -> str | None: ...
    def write(self, token: str) -> None: ...
    def delete(self) -> None: ...


class SignInRequired(RuntimeError):
    """The user must enter their tracker login again."""


class SupabaseAuth:
    def __init__(self, project_url: str, key: str, owner_id: str, store: TokenStore) -> None:
        self.project_url = project_url
        self.key = key
        self.owner_id = owner_id
        self.store = store
        self._access = ""
        self._expires_at = 0.0

    def sign_in(self, email: str, password: str) -> None:
        self._exchange("password", {"email": email.strip(), "password": password})

    def access_token(self) -> str:
        if self._access and time.time() < self._expires_at - 60:
            return self._access
        refresh = self.store.read()
        if not refresh:
            raise SignInRequired("Sign in to connect this computer.")
        self._exchange("refresh_token", {"refresh_token": refresh})
        return self._access

    def sign_out(self) -> None:
        self.store.delete()
        self._access = ""
        self._expires_at = 0

    def _exchange(self, grant: str, payload: dict[str, str]) -> None:
        request = Request(
            f"{self.project_url}/auth/v1/token?grant_type={grant}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"apikey": self.key, "Content-Type": "application/json"},
        )
        try:
            with build_opener(_NoRedirect()).open(request, timeout=10) as response:
                raw = response.read(65537)
        except HTTPError as error:
            if error.code in (400, 401, 403):
                raise SignInRequired(
                    "Tracker login was not accepted. Please sign in again."
                ) from None
            raise RuntimeError("Sync sign-in is temporarily unavailable.") from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("Cannot reach Supabase. Your local work remains saved.") from None
        if len(raw) > 65536:
            raise RuntimeError("Invalid sign-in response.")
        data = json.loads(raw)
        if data.get("user", {}).get("id") != self.owner_id:
            raise SignInRequired("Use the tracker account authorized for this project.")
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str) or not access or not refresh:
            raise RuntimeError("Invalid sign-in response.")
        self.store.write(refresh)
        self._access = access
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
