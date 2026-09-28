"""Versioned, allowlisted patient snapshots; never deserialize executable objects."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any
from uuid import UUID

from icu_patient_tracker.domain import enums
from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.diagnostic_result import DiagnosticResult
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.instrumentation import Instrumentation
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.problem_list import ProblemList
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.mapping import patient_from_record, patient_to_record

_CLASSES = {
    c.__name__: c
    for c in (
        Patient,
        HospitalDay,
        ProblemList,
        Problem,
        Instrumentation,
        Device,
        Task,
        Reminder,
        SOAPDocument,
        DiagnosticResult,
    )
}
_ENUMS = {
    name: cls
    for name, cls in vars(enums).items()
    if isinstance(cls, type) and issubclass(cls, Enum) and cls is not Enum
}


def encode_patient(patient: Patient | None) -> dict[str, object]:
    return {"schema_version": 1, "patient": _encode(patient)}


def decode_patient(payload: dict[str, object], expected_id: UUID) -> Patient | None:
    if set(payload) != {"schema_version", "patient"} or type(payload["schema_version"]) is not int:
        raise ValueError("Unrecognized patient sync format.")
    if payload["schema_version"] != 1:
        raise ValueError("This patient sync format requires a newer app.")
    result = _decode(payload["patient"])
    if result is None:
        return None
    if not isinstance(result, Patient) or result.id != expected_id:
        raise ValueError("Patient identity does not match its sync record.")
    # Reuse canonical persistence relationship validation and domain constructors.
    validated = patient_from_record(patient_to_record(result))
    if encode_patient(validated) != encode_patient(result):
        raise ValueError("Patient snapshot contains inconsistent relationships or ordering.")
    return validated


def dump_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"type": type(value).__name__, "value": value.value}
    if isinstance(value, (UUID, datetime, date, time)):
        return {"type": type(value).__name__, "value": str(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": type(value).__name__,
            "fields": {field.name: _encode(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, tuple):
        return {"type": "tuple", "value": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError("Unsupported patient snapshot field.")


def _decode(value: Any, depth: int = 0) -> Any:
    if depth > 30:
        raise ValueError("Patient snapshot is too deeply nested.")
    if isinstance(value, list):
        return [_decode(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("type")
    if kind in _CLASSES:
        cls = _CLASSES[kind]
        raw = value.get("fields")
        if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(cls)}:
            raise ValueError("Unknown or missing patient snapshot fields.")
        decoded = {key: _decode(item, depth + 1) for key, item in raw.items()}
        instance = cls(**{field.name: decoded[field.name] for field in fields(cls) if field.init})
        for field in fields(cls):
            if not field.init:
                setattr(instance, field.name, decoded[field.name])
        if "updated_at" in decoded:
            instance.updated_at = decoded["updated_at"]
        return instance
    if set(value) != {"type", "value"}:
        raise ValueError("Invalid snapshot field.")
    if kind in _ENUMS:
        return _ENUMS[kind](value["value"])
    if kind == "UUID":
        return UUID(value["value"])
    if kind == "datetime":
        return datetime.fromisoformat(value["value"])
    if kind == "date":
        return date.fromisoformat(value["value"])
    if kind == "time":
        return time.fromisoformat(value["value"])
    if kind == "tuple":
        return tuple(_decode(item, depth + 1) for item in value["value"])
    raise ValueError("Unknown snapshot type.")
