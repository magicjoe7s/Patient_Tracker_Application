"""Canonical SOAP Markdown authoring and conservative synchronization use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from icu_patient_tracker.domain.enums import (
    Acuity,
    CodeStatus,
    DeviceStatus,
    SOAPDocumentType,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.exceptions import DomainError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import (
    EventPublisher,
    HospitalDayChanged,
    InstrumentationChanged,
    PatientChanged,
    ProblemChanged,
    SOAPChanged,
)
from icu_patient_tracker.services.exceptions import InvalidOperationError, SOAPDocumentNotFoundError
from icu_patient_tracker.services.instrumentation_service import (
    device_line,
    device_output_label,
    reconcile_instrumentation_lines,
)
from icu_patient_tracker.services.soap_mapping import (
    CanonicalSOAPMapper,
    ParsedSOAP,
    SOAPDiagnosticResult,
    SOAPRenderContext,
)


@dataclass(frozen=True, slots=True)
class SOAPTemplate:
    """Optional initial legacy structured fields retained for API compatibility."""

    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


class SOAPService(ServiceBase):
    """Persist lossless Markdown while synchronizing only confidently recognized fields."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        publisher: EventPublisher | None = None,
        *,
        mapper: CanonicalSOAPMapper | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._mapper = mapper or CanonicalSOAPMapper()

    def create(
        self,
        patient_id: UUID,
        day_id: UUID,
        *,
        author: str,
        document_type: SOAPDocumentType = SOAPDocumentType.DAILY,
        template: SOAPTemplate | None = None,
        daytime_resident: str = "",
    ) -> SOAPDocument:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                content = template or SOAPTemplate()
                document = SOAPDocument(
                    patient_id,
                    day_id,
                    document_type,
                    author,
                    subjective=content.subjective,
                    objective=content.objective,
                    assessment=content.assessment,
                    plan=content.plan,
                )
                document.update_markdown(
                    self._mapper.render(self._context(patient, day, daytime_resident))
                )
                day.add_soap_document(document)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(SOAPChanged(str(document.id), "created"))
        return document

    def get(self, patient_id: UUID, day_id: UUID, document_id: UUID) -> SOAPDocument:
        with self._unit_of_work_factory() as unit_of_work:
            day = self._day(self._patient(unit_of_work, patient_id), day_id)
            return self._document(day, document_id)

    def ensure_markdown(
        self,
        patient_id: UUID,
        day_id: UUID,
        document_id: UUID,
        *,
        daytime_resident: str = "",
    ) -> SOAPDocument:
        """Initialize a pre-Slice-8 document once without replacing existing Markdown."""

        def ensure(document: SOAPDocument, patient: Patient, day: HospitalDay) -> None:
            if not document.markdown_text:
                document.update_markdown(
                    self._mapper.render(self._context(patient, day, daytime_resident))
                )

        return self._mutate(patient_id, day_id, document_id, "markdown_initialized", ensure)

    def update_sections(
        self, patient_id: UUID, day_id: UUID, document_id: UUID, **sections: str
    ) -> SOAPDocument:
        return self._mutate(
            patient_id,
            day_id,
            document_id,
            "updated",
            lambda document, _patient, _day: document.update_sections(**sections),
        )

    def save_markdown(
        self, patient_id: UUID, day_id: UUID, document_id: UUID, markdown_text: str
    ) -> SOAPDocument:
        """Store Markdown exactly and reverse-map only recognized, safe fields atomically."""
        parsed = self._mapper.parse(markdown_text)

        def save(document: SOAPDocument, patient: Patient, day: HospitalDay) -> None:
            document.update_markdown(markdown_text)
            self._synchronize_recognized(document, patient, day, parsed)

        document = self._mutate(patient_id, day_id, document_id, "markdown_saved", save)
        if parsed.code_status is not None or parsed.one_liner is not None:
            self._publisher.publish(PatientChanged(str(patient_id), "soap_patient_summary"))
        if parsed.clinical_trend is not None:
            self._publisher.publish(HospitalDayChanged(str(day_id), "soap_acuity"))
        if parsed.problems is not None:
            self._publisher.publish(ProblemChanged(str(day_id), "soap_problem_list"))
        if parsed.instrumentation is not None:
            self._publisher.publish(InstrumentationChanged(str(day_id), "soap_instrumentation"))
        return document

    def refresh_markdown(
        self,
        patient_id: UUID,
        day_id: UUID,
        document_id: UUID,
        *,
        sections: tuple[str, ...],
        daytime_resident: str = "",
    ) -> SOAPDocument:
        """Refresh only named canonical regions, leaving every other byte untouched."""

        def refresh(document: SOAPDocument, patient: Patient, day: HospitalDay) -> None:
            try:
                markdown = self._mapper.refresh(
                    document.markdown_text,
                    self._context(patient, day, daytime_resident),
                    sections,
                )
            except ValueError as error:
                raise InvalidOperationError(str(error)) from error
            document.update_markdown(markdown)
            if "problem_list" in sections:
                document.set_problem_references(
                    tuple(problem.id for problem in day.problem_list.active_problems)
                )

        return self._mutate(patient_id, day_id, document_id, "markdown_refreshed", refresh)

    def refresh_from_day(
        self,
        patient_id: UUID,
        day_id: UUID,
        document_id: UUID,
        *,
        sections: tuple[str, ...] = ("objective", "assessment", "plan"),
    ) -> SOAPDocument:
        """Retain the Phase V structured refresh API alongside canonical Markdown."""
        allowed = {"subjective", "objective", "assessment", "plan"}
        if not sections or set(sections) - allowed:
            raise InvalidOperationError("SOAP refresh sections must be recognized and non-empty.")

        def refresh(document: SOAPDocument, _patient: Patient, day: HospitalDay) -> None:
            generated = self._generated_sections(day)
            document.update_sections(**{name: generated[name] for name in sections})
            if "assessment" in sections:
                document.set_problem_references(
                    tuple(problem.id for problem in day.problem_list.active_problems)
                )

        return self._mutate(patient_id, day_id, document_id, "refreshed", refresh)

    def synchronize_to_day(
        self,
        patient_id: UUID,
        day_id: UUID,
        document_id: UUID,
        *,
        section_mapping: dict[str, str],
    ) -> HospitalDay:
        targets = {"treatment_changes", "physical_examination", "assessment", "clinical_summary"}
        sources = {"subjective", "objective", "assessment", "plan"}
        if (
            not section_mapping
            or set(section_mapping) - sources
            or set(section_mapping.values()) - targets
        ):
            raise InvalidOperationError("SOAP synchronization mapping contains an unknown section.")
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                document = self._document(day, document_id)
                changes = {
                    target: getattr(document, source) for source, target in section_mapping.items()
                }
                day.update_clinical_content(**changes)
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(SOAPChanged(str(document_id), "synchronized_to_day"))
        return day

    def _synchronize_recognized(
        self, document: SOAPDocument, patient: Patient, day: HospitalDay, parsed: ParsedSOAP
    ) -> None:
        if parsed.code_status is not None:
            code_status = self._parse_code_status(parsed.code_status)
            if code_status is not None:
                patient.update_summary(code_status=code_status)
        if parsed.clinical_trend is not None:
            acuity = self._parse_clinical_trend(parsed.clinical_trend)
            if acuity is not None:
                day.update_clinical_content(acuity=acuity)
        if parsed.one_liner is not None:
            patient.update_summary(one_line_summary=parsed.one_liner)
            document.subjective = parsed.one_liner
        physical_examination: str | None = None
        clinical_summary: str | None = None
        assessment: str | None = None
        treatment_changes: str | None = None
        if parsed.physical_examination is not None:
            physical_examination = parsed.physical_examination
            document.objective = parsed.physical_examination
        if parsed.diagnostic_summary is not None:
            clinical_summary = parsed.diagnostic_summary
        if parsed.assessment is not None:
            assessment = parsed.assessment
            document.assessment = parsed.assessment
        if parsed.treatment_changes is not None:
            treatment_changes = parsed.treatment_changes
            document.plan = parsed.treatment_changes
        mapped_values = physical_examination, clinical_summary, assessment, treatment_changes
        if any(value is not None for value in mapped_values):
            day.update_clinical_content(
                physical_examination=physical_examination,
                clinical_summary=clinical_summary,
                assessment=assessment,
                treatment_changes=treatment_changes,
            )
        if parsed.overnight_resident is not None or parsed.faculty is not None:
            day.update_soap_staff(
                overnight_resident=(
                    parsed.overnight_resident
                    if parsed.overnight_resident is not None
                    else day.overnight_resident
                ),
                faculty=parsed.faculty if parsed.faculty is not None else day.faculty,
            )
        self._synchronize_problem_titles(document, patient, day, parsed)
        if parsed.instrumentation is not None:
            reconcile_instrumentation_lines(day, parsed.instrumentation)

    @staticmethod
    def _synchronize_problem_titles(
        document: SOAPDocument, patient: Patient, day: HospitalDay, parsed: ParsedSOAP
    ) -> None:
        if parsed.problems is None:
            return
        existing_active = list(day.problem_list.active_problems)
        unused = list(existing_active)
        retained: list[Problem] = []
        for value in parsed.problems:
            title, *detail_lines = value.splitlines()
            description = "\n".join(detail_lines)
            selected = next((problem for problem in unused if problem.title == title), None)
            if selected is None and unused:
                selected = unused[0]
            if selected is None:
                selected = Problem(
                    patient.id,
                    day.id,
                    title,
                    description=description,
                    ordering_position=len(day.problem_list.problems),
                )
                day.problem_list.add(selected)
                source = selected
                for later_day in patient.hospital_days:
                    if later_day.day_number <= day.day_number:
                        continue
                    occurrence = Problem(
                        patient.id,
                        later_day.id,
                        title,
                        description=description,
                        ordering_position=len(later_day.problem_list.problems),
                        lineage_id=selected.lineage_id,
                        source_problem_id=source.id,
                        occurrence_number=source.occurrence_number + 1,
                    )
                    later_day.problem_list.add(occurrence)
                    source = occurrence
                retained.append(selected)
                continue
            unused.remove(selected)
            for candidate_day in patient.hospital_days:
                if candidate_day.day_number < day.day_number:
                    continue
                for problem in candidate_day.problem_list.problems:
                    if problem.lineage_id == selected.lineage_id:
                        problem.update_details(title=title, description=description)
            retained.append(selected)
        omitted = {problem.lineage_id for problem in unused}
        for candidate_day in patient.hospital_days:
            if candidate_day.day_number < day.day_number:
                continue
            for problem in tuple(candidate_day.problem_list.problems):
                if problem.lineage_id in omitted:
                    candidate_day.problem_list.remove(problem.id)
        non_active = [problem for problem in day.problem_list.problems if problem not in retained]
        day.problem_list.reorder([problem.id for problem in (*retained, *non_active)])
        ordered_lineages = [problem.lineage_id for problem in retained]
        for later_day in patient.hospital_days:
            if later_day.day_number <= day.day_number:
                continue
            by_lineage = {
                problem.lineage_id: problem for problem in later_day.problem_list.problems
            }
            ordered = [by_lineage[lineage] for lineage in ordered_lineages if lineage in by_lineage]
            ordered.extend(
                problem
                for problem in later_day.problem_list.problems
                if problem.lineage_id not in ordered_lineages
            )
            later_day.problem_list.reorder([problem.id for problem in ordered])
        document.set_problem_references(tuple(problem.id for problem in retained))

    @staticmethod
    def _generated_sections(day: HospitalDay) -> dict[str, str]:
        devices = (
            ", ".join(
                f"{device.device_type.value}: {device.anatomical_location}"
                for device in day.instrumentation.devices
                if device.status is DeviceStatus.ACTIVE
            )
            or "None"
        )
        problems = (
            "\n".join(
                f"- {problem.title}: {problem.assessment}"
                if problem.assessment
                else f"- {problem.title}"
                for problem in day.problem_list.active_problems
            )
            or day.assessment
        )
        tasks = (
            "\n".join(
                f"- {task.title}"
                for task in day.tasks
                if task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
            )
            or day.treatment_changes
        )
        return {
            "subjective": day.clinical_summary,
            "objective": f"{day.physical_examination}\nActive devices: {devices}".strip(),
            "assessment": problems,
            "plan": tasks,
        }

    @classmethod
    def _context(
        cls, patient: Patient, day: HospitalDay, daytime_resident: str
    ) -> SOAPRenderContext:
        active_devices = tuple(
            device for device in day.instrumentation.devices if device.status is DeviceStatus.ACTIVE
        )
        instrumentation = tuple(f"- {device_line(device)}" for device in active_devices)
        output_labels: list[str] = []
        for device in active_devices:
            label = device_output_label(device)
            if label is not None and label not in output_labels:
                output_labels.append(label)
        return SOAPRenderContext(
            day_number=day.day_number,
            calendar_date=day.calendar_date,
            code_status=cls._code_status(patient.code_status),
            clinical_trend=cls._clinical_trend(day.acuity),
            one_liner=patient.one_line_summary,
            problems=tuple(
                "\n".join(
                    (
                        problem.title,
                        *(
                            line.strip()
                            for line in problem.description.splitlines()
                            if line.strip()
                        ),
                    )
                )
                for problem in day.problem_list.active_problems
            ),
            physical_examination=day.physical_examination,
            diagnostic_summary=day.clinical_summary,
            diagnostic_results=tuple(
                SOAPDiagnosticResult(
                    task.title,
                    task.diagnostic_result.result_text if task.diagnostic_result else "",
                    task.status is TaskStatus.COMPLETED,
                )
                for task in day.tasks
                if task.category is TaskCategory.DIAGNOSTIC
                and task.status is not TaskStatus.CANCELLED
            ),
            treatment_changes=day.treatment_changes,
            instrumentation=instrumentation,
            device_output_labels=tuple(output_labels),
            assessment=day.assessment,
            daytime_resident=daytime_resident,
            overnight_resident=day.overnight_resident,
            faculty=day.faculty,
        )

    @staticmethod
    def _clinical_trend(acuity: Acuity) -> str:
        return {
            Acuity.UNKNOWN: "#INPUT#",
            Acuity.STABLE: "stable",
            Acuity.WATCHER: "watcher",
            Acuity.UNSTABLE: "unstable",
            Acuity.CRITICAL: "critical",
        }[acuity]

    @staticmethod
    def _code_status(status: CodeStatus) -> str:
        return {
            CodeStatus.FULL_CODE: "CPR",
            CodeStatus.DO_NOT_RESUSCITATE: "DNR",
            CodeStatus.DVM_DISCRETION: "DVM Discretion",
            CodeStatus.DNR_ASSIST: "DNR with assist",
            CodeStatus.LIMITED: "Limited",
            CodeStatus.UNKNOWN: "Unknown",
        }[status]

    @staticmethod
    def _parse_code_status(value: str) -> CodeStatus | None:
        return {
            "cpr": CodeStatus.FULL_CODE,
            "dnr": CodeStatus.DO_NOT_RESUSCITATE,
            "dvm discretion": CodeStatus.DVM_DISCRETION,
            "dnr with assist": CodeStatus.DNR_ASSIST,
            "dnr assist": CodeStatus.DNR_ASSIST,
        }.get(" ".join(value.split()).casefold())

    @staticmethod
    def _parse_clinical_trend(value: str) -> Acuity | None:
        return {
            "stable": Acuity.STABLE,
            "watcher": Acuity.WATCHER,
            "unstable": Acuity.UNSTABLE,
            "critical": Acuity.CRITICAL,
        }.get(" ".join(value.split()).casefold())

    def _mutate(
        self,
        patient_id: UUID,
        day_id: UUID,
        document_id: UUID,
        operation: str,
        action: Callable[[SOAPDocument, Patient, HospitalDay], None],
    ) -> SOAPDocument:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                document = self._document(day, document_id)
                action(document, patient, day)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(SOAPChanged(str(document_id), operation))
        return document

    @staticmethod
    def _document(day: HospitalDay, document_id: UUID) -> SOAPDocument:
        for document in day.soap_documents:
            if document.id == document_id:
                return document
        raise SOAPDocumentNotFoundError(f"SOAP document {document_id} was not found.")
