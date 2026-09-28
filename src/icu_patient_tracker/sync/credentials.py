"""Operating-system credential storage for a refresh token (never the password)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from importlib import import_module
from typing import Any, Protocol, cast


class TokenStore(Protocol):
    """Small credential-store contract consumed by Supabase authentication."""

    def read(self) -> str | None: ...

    def write(self, token: str) -> None: ...

    def delete(self) -> None: ...


class _KeyringBackend(Protocol):
    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, token: str) -> None: ...

    def delete_password(self, service: str, account: str) -> None: ...


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsTokenStore:
    def __init__(self, target: str) -> None:
        self.target = "ICUPatientTracker/" + target

    def _api(self) -> Any:
        if sys.platform != "win32":
            raise RuntimeError("Remembered sync login requires Windows Credential Manager.")
        api = ctypes.WinDLL("advapi32", use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        return api

    def read(self) -> str | None:
        api = self._api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise RuntimeError("Windows could not read the saved sync login.")
        try:
            record = pointer.contents
            return ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize).decode(
                "utf-8"
            )
        finally:
            api.CredFree(pointer)

    def write(self, token: str) -> None:
        encoded = token.encode("utf-8")
        if len(encoded) > 2560:
            raise ValueError("Sync refresh token exceeds Windows credential capacity.")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _Credential()
        credential.Type = 1
        credential.TargetName = self.target
        credential.UserName = "ICU Patient Tracker"
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = 2  # Local computer, not roaming.
        if not self._api().CredWriteW(ctypes.byref(credential), 0):
            raise RuntimeError("Windows could not save the sync login.")

    def delete(self) -> None:
        if not self._api().CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise RuntimeError("Windows could not remove the sync login.")


class MacOSTokenStore:
    """Store the refresh token in the user's macOS login Keychain."""

    def __init__(self, target: str, backend: _KeyringBackend | None = None) -> None:
        self.service = "ICUPatientTracker/" + target
        self.account = "refresh-token"
        if backend is None:
            try:
                backend = cast(_KeyringBackend, import_module("keyring"))
            except ImportError as error:
                raise RuntimeError(
                    "Remembered sync login requires macOS Keychain support."
                ) from error
        self._backend = backend

    def read(self) -> str | None:
        try:
            return self._backend.get_password(self.service, self.account)
        except Exception as error:
            raise RuntimeError("macOS could not read the saved sync login.") from error

    def write(self, token: str) -> None:
        try:
            self._backend.set_password(self.service, self.account, token)
        except Exception as error:
            raise RuntimeError("macOS could not save the sync login.") from error

    def delete(self) -> None:
        try:
            existing = self._backend.get_password(self.service, self.account)
            if existing is not None:
                self._backend.delete_password(self.service, self.account)
        except Exception as error:
            raise RuntimeError("macOS could not remove the sync login.") from error


def create_token_store(target: str) -> TokenStore:
    """Create the secure refresh-token store for the current operating system."""
    if sys.platform == "win32":
        return WindowsTokenStore(target)
    if sys.platform == "darwin":
        return MacOSTokenStore(target)
    raise RuntimeError("Remembered sync login is supported on Windows and macOS only.")
