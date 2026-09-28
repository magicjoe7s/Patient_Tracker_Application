"""Read-only parsing and non-sensitive dry-run reporting for legacy version-13 files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

VERSION = 13
PATIENT_FIELD_COUNT = 14
DAY_FIELD_COUNT = 18
VALID_STATUSES = frozenset({"Active", "Home", "IMC", "Archived", "Death"})
VALID_ACUITIES = frozenset({"Stable", "Watcher", "Critical"})
VALID_CODE_STATUSES = frozenset({"CPR", "DNR", "DVM Discretion", "DNR Assist"})
MAIN_SETTING_ARITY = {
    "WINDOW": 5,
    "PIN_MAIN_WINDOW": 2,
    "SHOW_BIN": 2,
    "SIDEBAR_MODE": 2,
    "SIDEBAR_TASK_KIND": 2,
    "LEFT_COLLAPSED": 2,
    "HIDE_DONE_TODO": 2,
    "HIDE_DONE_PENDING": 2,
    "HIDE_DONE_POCUS": 2,
    "HIDE_DONE_HOUSEKEEPING": 2,
    "SORT_MODE": 2,
    "THEME_MODE": 2,
    "SIDEBAR_FILTER": 2,
    "ACTIVE_ORDER": 2,
    "HOUSEKEEPING": 2,
}
LegacyTaskKind = Literal["todo", "pending", "pocus", "housekeeping"]


class LegacyFormatError(ValueError):
    """A line failed strict structural validation without exposing its contents."""

    def __init__(self, filename: str, line_number: int, code: str) -> None:
        self.filename = filename
        self.line_number = line_number
        self.code = code
        super().__init__(f"{filename}:{line_number}: {code}")


@dataclass(frozen=True, slots=True)
class LegacyPatient:
    """One decoded version-13 patient row, still independent of the domain model."""

    legacy_id: str
    name: str
    status: str
    acuity: str
    code_status: str
    problem_list: str
    one_liner: str
    blood_type: str
    patient_todo: str
    patient_pending: str
    day_order: tuple[str, ...]
    patient_pocus: str
    mrn: str | None
    source_file: str
    source_line: int


@dataclass(frozen=True, slots=True)
class LegacyDay:
    """One decoded version-13 hospital-day row."""

    patient_legacy_id: str
    day_key: str
    todo: str
    pending: str
    treatment: str
    reminders: str
    assessment: str
    soap_mode: bool
    soap_markdown: str
    devices: str
    physical_exam: str
    emr_uploaded: bool
    sandbox: str
    pocus: str
    overnight_resident: str
    faculty: str
    acuity: str
    source_file: str
    source_line: int


@dataclass(frozen=True, slots=True)
class LegacySetting:
    """One decoded device-local setting from the main source."""

    name: str
    values: tuple[str, ...]
    source_line: int


@dataclass(frozen=True, slots=True)
class LegacyTask:
    """One normalized task row with its legacy lineage identity intact."""

    legacy_id: str
    title: str
    done: bool
    priority: str
    bucket: str
    carry_forward: bool
    reminder: str
    reminder_anchor: str
    reminder_last_shown: str
    kind: LegacyTaskKind
    ordering_position: int


@dataclass(frozen=True, slots=True)
class LegacyFile:
    """Parsed contents and provenance for one immutable source file."""

    path: Path
    role: str
    fingerprint: str
    patients: tuple[LegacyPatient, ...]
    days: tuple[LegacyDay, ...]
    settings: tuple[LegacySetting, ...]

    @property
    def setting_count(self) -> int:
        return len(self.settings)


@dataclass(frozen=True, slots=True)
class LegacyDataset:
    """Cross-validated main and archive records."""

    main: LegacyFile
    archive: LegacyFile

    @property
    def patients(self) -> tuple[LegacyPatient, ...]:
        return self.main.patients + self.archive.patients

    @property
    def days(self) -> tuple[LegacyDay, ...]:
        return self.main.days + self.archive.days


@dataclass(frozen=True, slots=True)
class LegacyDryRunReport:
    """Safe summary that intentionally excludes names, IDs, and clinical text."""

    valid: bool
    patient_count: int
    day_count: int
    missing_mrn_count: int
    status_counts: dict[str, int]
    setting_count: int
    task_count: int
    warning_codes: tuple[str, ...]
    main_fingerprint: str | None
    archive_fingerprint: str | None
    errors: tuple[str, ...] = ()


class LegacyV13Parser:
    """Strictly read explicit version-13 paths without any write capability."""

    def parse_pair(self, main_path: Path, archive_path: Path) -> LegacyDataset:
        main = self.parse_file(main_path, expected_role="main")
        archive = self.parse_file(archive_path, expected_role="archive")
        dataset = LegacyDataset(main, archive)
        self._validate_dataset(dataset)
        return dataset

    def dry_run(self, main_path: Path, archive_path: Path) -> LegacyDryRunReport:
        """Return counts and safe error codes without emitting clinical source content."""
        try:
            dataset = self.parse_pair(main_path, archive_path)
        except (LegacyFormatError, OSError) as error:
            message = str(error) if isinstance(error, LegacyFormatError) else "source-read-failed"
            return LegacyDryRunReport(False, 0, 0, 0, {}, 0, 0, (), None, None, (message,))
        patients = dataset.patients
        task_count = 0
        for patient in patients:
            patient_lists: tuple[tuple[str, LegacyTaskKind], ...] = (
                (patient.patient_todo, "todo"),
                (patient.patient_pending, "pending"),
                (patient.patient_pocus, "pocus"),
            )
            task_count += sum(len(self.parse_task_list(text, kind)) for text, kind in patient_lists)
        for day in dataset.days:
            day_lists: tuple[tuple[str, LegacyTaskKind], ...] = (
                (day.todo, "todo"),
                (day.pending, "pending"),
                (day.pocus, "pocus"),
            )
            task_count += sum(len(self.parse_task_list(text, kind)) for text, kind in day_lists)
        housekeeping = next(
            (
                setting.values[0]
                for setting in dataset.main.settings
                if setting.name == "HOUSEKEEPING"
            ),
            "",
        )
        task_count += len(self.parse_task_list(housekeeping, "housekeeping"))
        warnings: list[str] = []
        if housekeeping.strip():
            warnings.append("global-housekeeping-requires-manual-review")
        if any(day.reminders.strip() for day in dataset.days):
            warnings.append("legacy-reminder-summary-preserved-in-day-summary")
        return LegacyDryRunReport(
            valid=True,
            patient_count=len(patients),
            day_count=len(dataset.days),
            missing_mrn_count=sum(patient.mrn is None for patient in patients),
            status_counts=dict(sorted(Counter(patient.status for patient in patients).items())),
            setting_count=dataset.main.setting_count,
            task_count=task_count,
            warning_codes=tuple(warnings),
            main_fingerprint=dataset.main.fingerprint,
            archive_fingerprint=dataset.archive.fingerprint,
        )

    def parse_file(self, path: Path, *, expected_role: str) -> LegacyFile:
        """Parse one explicit path and validate its declared role and record arity."""
        resolved = path.expanduser().resolve(strict=True)
        raw = resolved.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest().upper()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise LegacyFormatError(resolved.name, 1, "invalid-utf8") from error
        lines = text.splitlines()
        if not lines or lines[0] != f"VERSION|{VERSION}":
            raise LegacyFormatError(resolved.name, 1, "unsupported-version")
        role = "archive" if len(lines) > 1 and lines[1] == "FILE_ROLE|ARCHIVE" else "main"
        if role != expected_role:
            raise LegacyFormatError(resolved.name, 1, "unexpected-file-role")

        patients: list[LegacyPatient] = []
        days: list[LegacyDay] = []
        settings: list[LegacySetting] = []
        for line_number, line in enumerate(lines[1:], start=2):
            if not line:
                continue
            fields = line.split("|")
            record_type = fields[0]
            if record_type == "FILE_ROLE":
                if role != "archive" or line_number != 2 or fields != ["FILE_ROLE", "ARCHIVE"]:
                    raise LegacyFormatError(resolved.name, line_number, "invalid-file-role")
            elif record_type == "PATIENT":
                patients.append(self._parse_patient(resolved.name, line_number, fields))
            elif record_type == "DAY":
                days.append(self._parse_day(resolved.name, line_number, fields))
            elif record_type in MAIN_SETTING_ARITY:
                if role != "main" or len(fields) != MAIN_SETTING_ARITY[record_type]:
                    raise LegacyFormatError(resolved.name, line_number, "invalid-setting-record")
                settings.append(
                    LegacySetting(
                        record_type,
                        tuple(
                            self._decode(value, resolved.name, line_number) for value in fields[1:]
                        ),
                        line_number,
                    )
                )
            else:
                raise LegacyFormatError(resolved.name, line_number, "unknown-record-type")
        return LegacyFile(
            resolved,
            role,
            fingerprint,
            tuple(patients),
            tuple(days),
            tuple(settings),
        )

    def parse_task_list(
        self,
        text: str,
        kind: LegacyTaskKind,
    ) -> tuple[LegacyTask, ...]:
        """Decode normalized v13 checklist syntax without exposing text in errors."""
        tasks: list[LegacyTask] = []
        for position, raw_line in enumerate(text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[-*+]\s+", "", line)
            match = re.fullmatch(r"\[\s*([xX]?)\s*\]\s*(.*)", line)
            done = bool(match and match.group(1))
            body = match.group(2).strip() if match else line
            parts = [part.strip() for part in body.split("|")]
            title = parts[0]
            priority = "routine"
            bucket = "diagnostic" if kind == "pending" else "today"
            carry_forward = True
            reminder = reminder_anchor = reminder_last_shown = legacy_id = ""
            if title.startswith("!!"):
                title, priority = title[2:].strip(), "critical"
            elif title.startswith("!"):
                title, priority = title[1:].strip(), "urgent"
            for token in parts[1:]:
                lowered = token.lower()
                if match := re.fullmatch(r"id\s*:\s*(.+)", token, re.IGNORECASE):
                    legacy_id = re.sub(r"[\x00-\x20\x7f|]+", "", match.group(1).strip())
                elif lowered in {"nocarry", "no-carry", "carry:no", "carry:false"}:
                    carry_forward = False
                elif match := re.fullmatch(r"(?:p|priority)\s*:\s*(.+)", lowered):
                    priority = self._normalize_priority(match.group(1))
                elif match := re.fullmatch(r"(?:b|bucket)\s*:\s*(.+)", lowered):
                    bucket = self._normalize_bucket(match.group(1), kind)
                elif match := re.fullmatch(r"(?:r|remind|reminder)\s*:\s*(.+)", lowered):
                    reminder = self._normalize_reminder(match.group(1))
                elif match := re.fullmatch(r"(?:a|anchor)\s*:\s*(.+)", lowered):
                    reminder_anchor = self._normalize_timestamp(match.group(1))
                elif match := re.fullmatch(r"(?:ls|shown|lastshown|last)\s*:\s*(.+)", lowered):
                    reminder_last_shown = self._normalize_timestamp(match.group(1))
            if not title or not legacy_id:
                raise LegacyFormatError("legacy-task", position + 1, "invalid-task-record")
            tasks.append(
                LegacyTask(
                    legacy_id,
                    title,
                    done,
                    priority,
                    bucket,
                    carry_forward,
                    reminder,
                    reminder_anchor,
                    reminder_last_shown,
                    kind,
                    position,
                )
            )
        return tuple(tasks)

    @staticmethod
    def _normalize_priority(value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"critical", "crit", "stat"}:
            return "critical"
        if normalized in {"urgent", "high"}:
            return "urgent"
        return normalized if normalized == "low" else "routine"

    @staticmethod
    def _normalize_bucket(value: str, kind: str) -> str:
        normalized = value.strip().lower()
        aliases = {
            "day": "today",
            "am": "today",
            "night": "overnight",
            "pm": "overnight",
            "dc": "discharge",
            "follow-up": "followup",
            "f/u": "followup",
            "recheck": "followup",
            "pending": "diagnostic",
            "test": "diagnostic",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in {"today", "overnight", "discharge", "followup", "diagnostic"}:
            return normalized
        return "diagnostic" if kind == "pending" else "today"

    @staticmethod
    def _normalize_reminder(value: str) -> str:
        normalized = value.strip().lower()
        match = re.fullmatch(r"(\d{1,3})\s*(?:m|min|mins|minute|minutes)?", normalized)
        if match:
            return f"{int(match.group(1))}m"
        if match := re.fullmatch(r"(\d{1,2}):(\d{2})", normalized):
            hour, minute = map(int, match.groups())
            if hour <= 23 and minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        return ""

    @staticmethod
    def _normalize_timestamp(value: str) -> str:
        normalized = value.strip()
        if re.fullmatch(r"\d{12}", normalized):
            return normalized + "00"
        return normalized if re.fullmatch(r"\d{14}", normalized) else ""

    def _parse_patient(self, filename: str, line_number: int, fields: list[str]) -> LegacyPatient:
        if len(fields) != PATIENT_FIELD_COUNT:
            raise LegacyFormatError(filename, line_number, "invalid-patient-field-count")
        decoded = [self._decode(value, filename, line_number) for value in fields[1:]]
        legacy_id, name, status, acuity, code_status = decoded[:5]
        if not legacy_id or not name:
            raise LegacyFormatError(filename, line_number, "missing-patient-identity")
        if status not in VALID_STATUSES:
            raise LegacyFormatError(filename, line_number, "invalid-patient-status")
        if acuity not in VALID_ACUITIES:
            raise LegacyFormatError(filename, line_number, "invalid-patient-acuity")
        if code_status not in VALID_CODE_STATUSES:
            raise LegacyFormatError(filename, line_number, "invalid-code-status")
        mrn = decoded[12] or None
        if mrn is not None and re.fullmatch(r"\d{6}", mrn) is None:
            raise LegacyFormatError(filename, line_number, "invalid-mrn")
        return LegacyPatient(
            legacy_id=legacy_id,
            name=name,
            status=status,
            acuity=acuity,
            code_status=code_status,
            problem_list=decoded[5],
            one_liner=decoded[6],
            blood_type=decoded[7],
            patient_todo=decoded[8],
            patient_pending=decoded[9],
            day_order=tuple(value for value in decoded[10].split(",") if value),
            patient_pocus=decoded[11],
            mrn=mrn,
            source_file=filename,
            source_line=line_number,
        )

    def _parse_day(self, filename: str, line_number: int, fields: list[str]) -> LegacyDay:
        if len(fields) != DAY_FIELD_COUNT:
            raise LegacyFormatError(filename, line_number, "invalid-day-field-count")
        decoded = [self._decode(value, filename, line_number) for value in fields[1:]]
        if not decoded[0] or not decoded[1]:
            raise LegacyFormatError(filename, line_number, "missing-day-identity")
        if decoded[7] not in {"0", "1"} or decoded[11] not in {"0", "1"}:
            raise LegacyFormatError(filename, line_number, "invalid-day-boolean")
        if decoded[16] not in VALID_ACUITIES:
            raise LegacyFormatError(filename, line_number, "invalid-day-acuity")
        return LegacyDay(
            patient_legacy_id=decoded[0],
            day_key=decoded[1],
            todo=decoded[2],
            pending=decoded[3],
            treatment=decoded[4],
            reminders=decoded[5],
            assessment=decoded[6],
            soap_mode=decoded[7] == "1",
            soap_markdown=decoded[8],
            devices=decoded[9],
            physical_exam=decoded[10],
            emr_uploaded=decoded[11] == "1",
            sandbox=decoded[12],
            pocus=decoded[13],
            overnight_resident=decoded[14],
            faculty=decoded[15],
            acuity=decoded[16],
            source_file=filename,
            source_line=line_number,
        )

    @staticmethod
    def _decode(value: str, filename: str, line_number: int) -> str:
        output = bytearray()
        index = 0
        while index < len(value):
            if value[index] == "%":
                token = value[index + 1 : index + 3]
                if len(token) != 2 or re.fullmatch(r"[0-9A-Fa-f]{2}", token) is None:
                    raise LegacyFormatError(filename, line_number, "invalid-percent-escape")
                output.append(int(token, 16))
                index += 3
            else:
                codepoint = ord(value[index])
                if codepoint > 127:
                    raise LegacyFormatError(filename, line_number, "unescaped-non-ascii")
                output.append(codepoint)
                index += 1
        try:
            return output.decode("utf-8")
        except UnicodeDecodeError as error:
            raise LegacyFormatError(filename, line_number, "invalid-encoded-utf8") from error

    @staticmethod
    def _validate_dataset(dataset: LegacyDataset) -> None:
        patients = dataset.patients
        legacy_ids = [patient.legacy_id for patient in patients]
        if len(legacy_ids) != len(set(legacy_ids)):
            raise LegacyFormatError("legacy-dataset", 0, "duplicate-patient-identity")
        mrns = [patient.mrn for patient in patients if patient.mrn is not None]
        if len(mrns) != len(set(mrns)):
            raise LegacyFormatError("legacy-dataset", 0, "duplicate-mrn")
        patient_ids = set(legacy_ids)
        day_keys: set[tuple[str, str]] = set()
        for day in dataset.days:
            if day.patient_legacy_id not in patient_ids:
                raise LegacyFormatError(day.source_file, day.source_line, "orphan-day")
            key = (day.patient_legacy_id, day.day_key)
            if key in day_keys:
                raise LegacyFormatError(day.source_file, day.source_line, "duplicate-day")
            day_keys.add(key)
        for patient in patients:
            actual = {key for owner, key in day_keys if owner == patient.legacy_id}
            if set(patient.day_order) != actual:
                raise LegacyFormatError(
                    patient.source_file, patient.source_line, "day-order-mismatch"
                )
            expected_role = "main" if patient.status == "Active" else "archive"
            source_role = (
                dataset.main.role
                if patient.source_file == dataset.main.path.name
                else dataset.archive.role
            )
            if source_role != expected_role:
                raise LegacyFormatError(
                    patient.source_file, patient.source_line, "patient-in-wrong-file"
                )


def main(arguments: Sequence[str] | None = None) -> int:
    """Print a non-sensitive JSON dry-run report for two explicit source paths."""
    argument_parser = argparse.ArgumentParser(
        description="Validate legacy version-13 tracker data."
    )
    argument_parser.add_argument("main_file", type=Path)
    argument_parser.add_argument("archive_file", type=Path)
    parsed = argument_parser.parse_args(arguments)
    report = LegacyV13Parser().dry_run(parsed.main_file, parsed.archive_file)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
