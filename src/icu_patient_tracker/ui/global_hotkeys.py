"""Best-effort Windows global hotkeys for the resident desktop shell."""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
_CTYPES: Any = ctypes


@dataclass(frozen=True, slots=True)
class GlobalHotkey:
    """One operating-system hotkey and its in-process callback."""

    identifier: int
    label: str
    modifiers: int
    virtual_key: int
    callback: Callable[[], None]


class HotkeyBackend(Protocol):
    """Boundary around the Windows user32 hotkey API."""

    def register(self, identifier: int, modifiers: int, virtual_key: int) -> bool:
        """Register a process-global key combination."""

    def unregister(self, identifier: int) -> None:
        """Release a previously registered key combination."""


class WindowsHotkeyBackend:
    """Register global shortcuts through the Windows user32 API."""

    def __init__(self) -> None:
        self._user32 = _CTYPES.WinDLL("user32", use_last_error=True)

    def register(self, identifier: int, modifiers: int, virtual_key: int) -> bool:
        return bool(self._user32.RegisterHotKey(None, identifier, modifiers, virtual_key))

    def unregister(self, identifier: int) -> None:
        self._user32.UnregisterHotKey(None, identifier)


class _NativeHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, dispatch: Callable[[int], bool]) -> None:
        super().__init__()
        self._dispatch = dispatch

    def nativeEventFilter(
        self,
        event_type: QByteArray | bytes | bytearray | memoryview[int],
        message: int,
    ) -> tuple[bool, int]:
        del event_type
        native_message = wintypes.MSG.from_address(int(message))
        if native_message.message == WM_HOTKEY:
            return self._dispatch(int(native_message.wParam)), 0
        return False, 0


class GlobalHotkeyManager:
    """Register, dispatch, and reliably release the supported global shortcuts."""

    def __init__(
        self,
        callbacks: Mapping[str, Callable[[], None]],
        *,
        backend: HotkeyBackend | None = None,
        application: QCoreApplication | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger("icu_patient_tracker")
        self._application = application or QCoreApplication.instance()
        self._backend = backend
        if self._backend is None and sys.platform == "win32":
            self._backend = WindowsHotkeyBackend()
        self._hotkeys = {
            hotkey.identifier: hotkey
            for hotkey in (
                GlobalHotkey(
                    0x4950,
                    "Shift+Alt+I",
                    MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
                    ord("I"),
                    callbacks["toggle_application"],
                ),
                GlobalHotkey(
                    0x4951,
                    "Alt+Shift+T",
                    MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
                    ord("T"),
                    callbacks["toggle_task_board"],
                ),
                GlobalHotkey(
                    0x4952,
                    "Alt+Shift+R",
                    MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
                    ord("R"),
                    callbacks["capture_diagnostic_result"],
                ),
            )
        }
        self._registered: set[int] = set()
        self._filter = _NativeHotkeyFilter(self.dispatch)

    @property
    def registered_labels(self) -> tuple[str, ...]:
        """Return successfully registered shortcuts for status and tests."""
        return tuple(self._hotkeys[key].label for key in sorted(self._registered))

    def start(self) -> None:
        """Install the native filter and register shortcuts when supported."""
        if self._backend is None or self._application is None:
            self._logger.info("Global hotkeys are unavailable on this platform")
            return
        self._application.installNativeEventFilter(self._filter)
        for identifier, hotkey in self._hotkeys.items():
            if self._backend.register(identifier, hotkey.modifiers, hotkey.virtual_key):
                self._registered.add(identifier)
                self._logger.info("Registered global hotkey", extra={"hotkey": hotkey.label})
            else:
                self._logger.warning(
                    "Unable to register global hotkey; another application may own it",
                    extra={"hotkey": hotkey.label},
                )

    def dispatch(self, identifier: int) -> bool:
        """Invoke one registered hotkey callback from the native event filter."""
        hotkey = self._hotkeys.get(identifier)
        if hotkey is None or identifier not in self._registered:
            return False
        hotkey.callback()
        return True

    def stop(self) -> None:
        """Unregister every acquired shortcut and remove the native event filter."""
        if self._backend is not None:
            for identifier in tuple(self._registered):
                self._backend.unregister(identifier)
        self._registered.clear()
        if self._application is not None:
            self._application.removeNativeEventFilter(self._filter)
