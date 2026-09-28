"""Atomic device-local storage for transient unsaved-editor recovery snapshots."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from icu_patient_tracker.persistence.exceptions import RecoveryError

RECOVERY_VERSION = 1


@dataclass(frozen=True, slots=True)
class RecoveryEntry:
    """One editor's values and the fingerprint of the canonical values it loaded."""

    key: str
    base_fingerprint: str
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    """Unsaved editor values for one stable patient/day context."""

    patient_id: UUID
    hospital_day_id: UUID | None
    created_at: datetime
    entries: tuple[RecoveryEntry, ...]


class RecoveryStore:
    """Read, atomically replace, and archive one local recovery document."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def load(self) -> RecoverySnapshot | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._parse(raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RecoveryError("The recovery snapshot is invalid or unreadable.") from error

    def write(self, snapshot: RecoverySnapshot) -> None:
        payload = {
            "version": RECOVERY_VERSION,
            "patient_id": str(snapshot.patient_id),
            "hospital_day_id": (
                str(snapshot.hospital_day_id) if snapshot.hospital_day_id is not None else None
            ),
            "created_at": snapshot.created_at.astimezone(UTC).isoformat(),
            "entries": [
                {
                    "key": entry.key,
                    "base_fingerprint": entry.base_fingerprint,
                    "values": entry.values,
                }
                for entry in snapshot.entries
            ],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise RecoveryError("The recovery snapshot could not be written.") from error

    def clear(self) -> Path | None:
        """Archive the last snapshot, then remove the active recovery marker."""
        if not self.path.exists():
            return None
        archived = self.path.with_suffix(f"{self.path.suffix}.bak")
        try:
            shutil.copy2(self.path, archived)
            self.path.unlink()
        except OSError as error:
            raise RecoveryError("The recovery snapshot could not be cleared.") from error
        return archived

    @staticmethod
    def _parse(raw: object) -> RecoverySnapshot:
        if not isinstance(raw, dict) or raw.get("version") != RECOVERY_VERSION:
            raise ValueError("Unsupported recovery snapshot version.")
        patient_id = UUID(_required_string(raw, "patient_id"))
        raw_day_id = raw.get("hospital_day_id")
        if raw_day_id is not None and not isinstance(raw_day_id, str):
            raise ValueError("Invalid recovery day identity.")
        hospital_day_id = UUID(raw_day_id) if raw_day_id else None
        created_at = datetime.fromisoformat(_required_string(raw, "created_at"))
        if created_at.tzinfo is None:
            raise ValueError("Recovery timestamp must be timezone-aware.")
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("Recovery snapshot has no editor entries.")
        entries: list[RecoveryEntry] = []
        seen: set[str] = set()
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValueError("Invalid recovery entry.")
            key = _required_string(raw_entry, "key")
            if key in seen:
                raise ValueError("Duplicate recovery entry.")
            fingerprint = _required_string(raw_entry, "base_fingerprint")
            values = raw_entry.get("values")
            if not isinstance(values, dict) or not all(
                isinstance(name, str) and isinstance(value, str) for name, value in values.items()
            ):
                raise ValueError("Recovery values must be text fields.")
            seen.add(key)
            entries.append(RecoveryEntry(key, fingerprint, dict(values)))
        return RecoverySnapshot(patient_id, hospital_day_id, created_at, tuple(entries))


def _required_string(raw: dict[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Recovery field {key!r} must be non-empty text.")
    return value
