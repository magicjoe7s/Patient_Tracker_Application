"""Confirmed, atomic, and repeat-safe import of legacy version-13 records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import URL, Engine, create_engine, func, select, text
from sqlalchemy.orm import Session

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    ClinicalPriority,
    CodeStatus,
    DeviceType,
    ReminderScheduleType,
    ReminderStatus,
    SOAPDocumentType,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.backup import BackupManager
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.legacy_v13 import (
    VERSION,
    LegacyDataset,
    LegacyDay,
    LegacyTask,
    LegacyTaskKind,
    LegacyV13Parser,
)
from icu_patient_tracker.persistence.mapping import patient_to_record
from icu_patient_tracker.persistence.orm_models import (
    DeviceRecord,
    HospitalDayRecord,
    PatientRecord,
    ProblemRecord,
    ReminderRecord,
    SOAPDocumentRecord,
    TaskRecord,
)


class LegacyImportError(RuntimeError):
    """The import was rejected without exposing clinical source content."""


@dataclass(frozen=True, slots=True)
class LegacyImportCounts:
    patient_count: int
    day_count: int
    task_count: int
    problem_count: int
    soap_count: int
    device_count: int
    reminder_count: int
    setting_count: int


@dataclass(frozen=True, slots=True)
class LegacyImportReport:
    """Non-clinical result suitable for terminal output and audit review."""

    imported: bool
    run_id: str
    main_fingerprint: str
    archive_fingerprint: str
    backup_path: str
    counts: LegacyImportCounts
    warning_codes: tuple[str, ...]
    reconciled: bool


@dataclass(slots=True)
class _MappedImport:
    patients: list[Patient]
    identities: list[tuple[str, str, UUID]]
    counts: LegacyImportCounts
    warnings: set[str]


class LegacyV13Importer:
    """Map and commit a reviewed source pair to an empty SQLite target."""

    def __init__(self, *, timezone_name: str = "America/New_York") -> None:
        self._timezone: tzinfo
        if timezone_name.upper() == "UTC":
            self._timezone = UTC
        else:
            try:
                self._timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as error:
                raise LegacyImportError(
                    "unknown-import-timezone-install-project-dependencies"
                ) from error
        self._parser = LegacyV13Parser()

    def import_to(
        self,
        main_path: Path,
        archive_path: Path,
        target_path: Path,
        backup_directory: Path,
        *,
        confirmation: str,
    ) -> LegacyImportReport:
        """Back up, atomically import, reconcile, and verify unchanged sources."""
        dataset = self._parser.parse_pair(main_path, archive_path)
        expected_confirmation = self.confirmation_token(dataset)
        if confirmation.strip().upper() != expected_confirmation:
            raise LegacyImportError("source-confirmation-mismatch")

        mapped = self._map_dataset(dataset)
        target = target_path.expanduser().resolve()
        manager = DatabaseManager(target)
        manager.initialize()
        manager.dispose()
        backup = BackupManager(target, backup_directory, retention_count=10).create_backup(
            label="pre_legacy_import"
        )
        run_id = uuid4().hex
        engine = create_engine(URL.create("sqlite", database=str(target)))
        try:
            with Session(engine) as session, session.begin():
                duplicate = session.scalar(
                    text(
                        "SELECT 1 FROM legacy_import_runs "
                        "WHERE main_sha256=:main AND archive_sha256=:archive"
                    ),
                    {"main": dataset.main.fingerprint, "archive": dataset.archive.fingerprint},
                )
                if duplicate is not None:
                    raise LegacyImportError("source-pair-already-imported")
                if (session.scalar(select(func.count()).select_from(PatientRecord)) or 0) != 0:
                    raise LegacyImportError("target-database-is-not-empty")
                for patient in mapped.patients:
                    session.add(patient_to_record(patient))
                session.flush()
                session.execute(
                    text(
                        "INSERT INTO legacy_import_runs "
                        "(id, main_sha256, archive_sha256, source_version, imported_at, "
                        "patient_count, day_count, task_count, problem_count, soap_count, "
                        "device_count, reminder_count, setting_count, warning_count) VALUES "
                        "(:id, :main, :archive, :version, :at, :patients, :days, :tasks, "
                        ":problems, :soap, :devices, :reminders, :settings, :warnings)"
                    ),
                    {
                        "id": run_id,
                        "main": dataset.main.fingerprint,
                        "archive": dataset.archive.fingerprint,
                        "version": VERSION,
                        "at": datetime.now(UTC).isoformat(),
                        "patients": mapped.counts.patient_count,
                        "days": mapped.counts.day_count,
                        "tasks": mapped.counts.task_count,
                        "problems": mapped.counts.problem_count,
                        "soap": mapped.counts.soap_count,
                        "devices": mapped.counts.device_count,
                        "reminders": mapped.counts.reminder_count,
                        "settings": mapped.counts.setting_count,
                        "warnings": len(mapped.warnings),
                    },
                )
                session.execute(
                    text(
                        "INSERT INTO legacy_identity_map "
                        "(import_run_id, entity_type, legacy_identity_sha256, target_uuid) "
                        "VALUES (:run, :kind, :legacy, :target)"
                    ),
                    [
                        {
                            "run": run_id,
                            "kind": kind,
                            "legacy": self._identity_hash(identity),
                            "target": target_uuid.hex,
                        }
                        for kind, identity, target_uuid in mapped.identities
                    ],
                )
            actual = self._database_counts(engine)
            reconciled = actual == mapped.counts
            if not reconciled:
                raise LegacyImportError("post-import-reconciliation-failed")
        finally:
            engine.dispose()

        after = self._parser.parse_pair(main_path, archive_path)
        if (
            after.main.fingerprint != dataset.main.fingerprint
            or after.archive.fingerprint != dataset.archive.fingerprint
        ):
            raise LegacyImportError("source-files-changed-during-import")
        return LegacyImportReport(
            True,
            run_id,
            dataset.main.fingerprint,
            dataset.archive.fingerprint,
            str(backup),
            mapped.counts,
            tuple(sorted(mapped.warnings)),
            True,
        )

    @staticmethod
    def confirmation_token(dataset: LegacyDataset) -> str:
        """Bind approval to the exact two reviewed source byte streams."""
        return f"{dataset.main.fingerprint}:{dataset.archive.fingerprint}"

    def _map_dataset(self, dataset: LegacyDataset) -> _MappedImport:
        days_by_owner: dict[str, list[LegacyDay]] = {
            patient.legacy_id: [] for patient in dataset.patients
        }
        for legacy_day in dataset.days:
            days_by_owner[legacy_day.patient_legacy_id].append(legacy_day)
        active_order = self._active_order(dataset)
        mapped: list[Patient] = []
        identities: list[tuple[str, str, UUID]] = []
        warnings: set[str] = {
            "device-local-settings-retained-in-source-not-applied",
            "legacy-completion-times-approximated-at-day-start",
        }
        total_tasks = total_problems = total_soap = total_devices = total_reminders = 0
        for source_patient in dataset.patients:
            patient = Patient(
                name=source_patient.name,
                species="Unknown",
                mrn=source_patient.mrn,
                one_line_summary=source_patient.one_liner,
                code_status=self._code_status(source_patient.code_status),
                blood_type=source_patient.blood_type or None,
                acuity=self._acuity(source_patient.acuity),
                admission_status=self._admission_status(source_patient.status),
                active_order=active_order.get(source_patient.legacy_id, 0),
            )
            identities.append(("patient", source_patient.legacy_id, patient.id))
            source_days = sorted(
                days_by_owner[source_patient.legacy_id],
                key=lambda item: self._day_date(item.day_key),
            )
            lineage_ids: dict[str, UUID] = {}
            latest_occurrence: dict[str, Task] = {}
            seen_task_ids: set[str] = set()
            for day_number, source_day in enumerate(source_days, start=1):
                calendar_date = self._day_date(source_day.day_key)
                start_at = datetime.combine(calendar_date, time(), tzinfo=self._timezone)
                day = HospitalDay(
                    patient_id=patient.id,
                    calendar_date=calendar_date,
                    day_number=day_number,
                    start_at=start_at,
                    acuity=self._acuity(source_day.acuity),
                    treatment_changes=source_day.treatment,
                    physical_examination=source_day.physical_exam,
                    assessment=source_day.assessment,
                    clinical_summary=source_day.reminders,
                    overnight_resident=source_day.overnight_resident,
                    faculty=source_day.faculty,
                    sandbox_text=source_day.sandbox,
                    emr_uploaded=source_day.emr_uploaded,
                )
                identities.append(
                    ("day", f"{source_patient.legacy_id}\0{source_day.day_key}", day.id)
                )
                day_task_lists: tuple[tuple[str, LegacyTaskKind], ...] = (
                    (source_day.todo, "todo"),
                    (source_day.pending, "pending"),
                    (source_day.pocus, "pocus"),
                )
                for task_text, kind in day_task_lists:
                    for legacy_task in self._parser.parse_task_list(task_text, kind):
                        task = self._map_task(
                            legacy_task, patient.id, day, lineage_ids, latest_occurrence
                        )
                        day.add_task(task)
                        seen_task_ids.add(legacy_task.legacy_id)
                        total_tasks += 1
                        if task.reminder is not None:
                            total_reminders += 1
                for line in source_day.devices.splitlines():
                    if line.strip():
                        day.instrumentation.add(
                            Device(
                                patient.id,
                                day.id,
                                DeviceType.OTHER,
                                line.strip(),
                                start_at,
                                notes=line,
                            )
                        )
                        total_devices += 1
                        warnings.add("legacy-devices-imported-as-other-free-text")
                if source_day.soap_markdown or source_day.soap_mode:
                    day.add_soap_document(
                        SOAPDocument(
                            patient.id,
                            day.id,
                            SOAPDocumentType.DAILY,
                            "Legacy import",
                            markdown_text=source_day.soap_markdown,
                        )
                    )
                    total_soap += 1
                patient.add_hospital_day(day)
            if source_days:
                latest_day = patient.hospital_days[-1]
                patient_task_lists: tuple[tuple[str, LegacyTaskKind], ...] = (
                    (source_patient.patient_todo, "todo"),
                    (source_patient.patient_pending, "pending"),
                    (source_patient.patient_pocus, "pocus"),
                )
                for task_text, kind in patient_task_lists:
                    for legacy_task in self._parser.parse_task_list(task_text, kind):
                        if legacy_task.legacy_id not in seen_task_ids:
                            task = self._map_task(
                                legacy_task,
                                patient.id,
                                latest_day,
                                lineage_ids,
                                latest_occurrence,
                            )
                            latest_day.add_task(task)
                            total_tasks += 1
                            if task.reminder is not None:
                                total_reminders += 1
                            warnings.add("patient-level-task-attached-to-latest-day")
                for position, title in enumerate(source_patient.problem_list.splitlines()):
                    if title.strip():
                        latest_day.problem_list.add(
                            Problem(
                                patient.id,
                                latest_day.id,
                                title.strip(),
                                ordering_position=position,
                                identified_at=latest_day.start_at,
                            )
                        )
                        total_problems += 1
                if source_patient.problem_list.strip():
                    warnings.add("running-problem-list-attached-to-latest-day")
            elif source_patient.problem_list.strip():
                warnings.add("patient-without-day-problem-list-retained-in-source-only")
            mapped.append(patient)

        housekeeping = next(
            (
                setting.values[0]
                for setting in dataset.main.settings
                if setting.name == "HOUSEKEEPING"
            ),
            "",
        )
        if housekeeping.strip():
            warnings.add("global-housekeeping-retained-in-source-requires-manual-review")
        counts = LegacyImportCounts(
            len(mapped),
            len(dataset.days),
            total_tasks,
            total_problems,
            total_soap,
            total_devices,
            total_reminders,
            dataset.main.setting_count,
        )
        return _MappedImport(mapped, identities, counts, warnings)

    def _map_task(
        self,
        source: LegacyTask,
        patient_id: UUID,
        day: HospitalDay,
        lineage_ids: dict[str, UUID],
        latest: dict[str, Task],
    ) -> Task:
        previous = latest.get(source.legacy_id)
        lineage_id = lineage_ids.setdefault(source.legacy_id, uuid4())
        task = Task(
            patient_id,
            day.id,
            source.title,
            status=TaskStatus.COMPLETED if source.done else TaskStatus.PENDING,
            priority=ClinicalPriority(source.priority),
            completed_at=day.start_at if source.done else None,
            category={
                "todo": TaskCategory.CLINICAL,
                "pending": TaskCategory.DIAGNOSTIC,
                "pocus": TaskCategory.POCUS,
                "housekeeping": TaskCategory.HOUSEKEEPING,
            }[source.kind],
            bucket=TaskBucket.FOLLOW_UP
            if source.bucket == "followup"
            else TaskBucket(source.bucket),
            source="legacy-v13",
            lineage_id=lineage_id,
            source_task_id=previous.id if previous is not None else None,
            occurrence_number=previous.occurrence_number + 1 if previous is not None else 1,
            carry_forward=source.carry_forward,
        )
        reminder = self._map_reminder(source, task, day)
        if reminder is not None:
            task.attach_reminder(reminder)
        latest[source.legacy_id] = task
        return task

    def _map_reminder(self, source: LegacyTask, task: Task, day: HospitalDay) -> Reminder | None:
        if not source.reminder:
            return None
        shown = self._legacy_timestamp(source.reminder_last_shown)
        status = (
            ReminderStatus.COMPLETED
            if task.status is TaskStatus.COMPLETED
            else ReminderStatus.PENDING
        )
        completed_at = day.start_at if status is ReminderStatus.COMPLETED else None
        if source.reminder.endswith("m"):
            minutes = int(source.reminder[:-1])
            anchor = self._legacy_timestamp(source.reminder_anchor) or day.start_at
            trigger = (shown or anchor) + timedelta(minutes=minutes)
            return Reminder(
                task.id,
                task.patient_id,
                task.hospital_day_id,
                trigger,
                task.title,
                ReminderScheduleType.INTERVAL,
                interval_minutes=minutes,
                anchor_at=anchor,
                status=status,
                completed_at=completed_at,
                last_shown_at=shown,
            )
        hour, minute = map(int, source.reminder.split(":"))
        trigger = datetime.combine(day.calendar_date, time(hour, minute), tzinfo=self._timezone)
        if shown is not None and shown >= trigger:
            trigger += timedelta(days=1)
        return Reminder(
            task.id,
            task.patient_id,
            task.hospital_day_id,
            trigger,
            task.title,
            ReminderScheduleType.FIXED_TIME,
            fixed_time=time(hour, minute),
            status=status,
            completed_at=completed_at,
            last_shown_at=shown,
        )

    def _legacy_timestamp(self, value: str) -> datetime | None:
        if not value:
            return None
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=self._timezone)

    @staticmethod
    def _day_date(day_key: str) -> date:
        match = re.search(r"\d{4}-\d{2}-\d{2}", day_key)
        if match is None:
            raise LegacyImportError("invalid-day-date")
        try:
            return date.fromisoformat(match.group())
        except ValueError as error:
            raise LegacyImportError("invalid-day-date") from error

    @staticmethod
    def _active_order(dataset: LegacyDataset) -> dict[str, int]:
        value = next(
            (
                setting.values[0]
                for setting in dataset.main.settings
                if setting.name == "ACTIVE_ORDER"
            ),
            "",
        )
        return {
            legacy_id: position for position, legacy_id in enumerate(value.split(",")) if legacy_id
        }

    @staticmethod
    def _admission_status(value: str) -> AdmissionStatus:
        return {
            "Active": AdmissionStatus.ADMITTED,
            "Home": AdmissionStatus.DISCHARGED,
            "IMC": AdmissionStatus.TRANSFERRED,
            "Archived": AdmissionStatus.ARCHIVED,
            "Death": AdmissionStatus.DECEASED,
        }[value]

    @staticmethod
    def _code_status(value: str) -> CodeStatus:
        return {
            "CPR": CodeStatus.FULL_CODE,
            "DNR": CodeStatus.DO_NOT_RESUSCITATE,
            "DVM Discretion": CodeStatus.DVM_DISCRETION,
            "DNR Assist": CodeStatus.DNR_ASSIST,
        }[value]

    @staticmethod
    def _acuity(value: str) -> Acuity:
        return Acuity(value.lower())

    @staticmethod
    def _identity_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()

    @staticmethod
    def _database_counts(engine: Engine) -> LegacyImportCounts:
        with Session(engine) as session:

            def scalar_count(model: Any) -> int:
                return int(session.scalar(select(func.count()).select_from(model)) or 0)

            setting_count = int(
                session.scalar(text("SELECT setting_count FROM legacy_import_runs")) or 0
            )
            return LegacyImportCounts(
                scalar_count(PatientRecord),
                scalar_count(HospitalDayRecord),
                scalar_count(TaskRecord),
                scalar_count(ProblemRecord),
                scalar_count(SOAPDocumentRecord),
                scalar_count(DeviceRecord),
                scalar_count(ReminderRecord),
                setting_count,
            )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run an explicitly confirmed import against an explicit SQLite target."""
    parser = argparse.ArgumentParser(description="Import reviewed legacy v13 data once.")
    parser.add_argument("main_file", type=Path)
    parser.add_argument("archive_file", type=Path)
    parser.add_argument("target_database", type=Path)
    parser.add_argument("--backup-directory", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--timezone", default="America/New_York")
    parsed = parser.parse_args(arguments)
    try:
        report = LegacyV13Importer(timezone_name=parsed.timezone).import_to(
            parsed.main_file,
            parsed.archive_file,
            parsed.target_database,
            parsed.backup_directory,
            confirmation=parsed.confirm,
        )
    except (LegacyImportError, OSError, ValueError) as error:
        print(json.dumps({"imported": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
