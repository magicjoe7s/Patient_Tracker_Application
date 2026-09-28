"""Problem-list application use cases."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from icu_patient_tracker.domain.enums import ClinicalPriority, ProblemStatus
from icu_patient_tracker.domain.exceptions import DomainError, EntityNotFoundError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase
from icu_patient_tracker.services.events import ProblemChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError, ResourceNotFoundError
from icu_patient_tracker.utils.problem_list_text import ProblemListEntry


@dataclass(frozen=True, slots=True)
class ProblemCarryForwardPolicy:
    """Create independent next-day occurrences for unresolved problems only."""

    def create_occurrences(self, source: HospitalDay, target: HospitalDay) -> tuple[Problem, ...]:
        existing_lineages = {problem.lineage_id for problem in target.problem_list.problems}
        created: list[Problem] = []
        for problem in source.problem_list.active_problems:
            if problem.lineage_id in existing_lineages:
                continue
            occurrence = Problem(
                patient_id=target.patient_id,
                hospital_day_id=target.id,
                title=problem.title,
                description=problem.description,
                status=problem.status,
                priority=problem.priority,
                identified_at=problem.identified_at,
                assessment=problem.assessment,
                plan=problem.plan,
                notes=problem.notes,
                ordering_position=len(target.problem_list.problems),
                lineage_id=problem.lineage_id,
                source_problem_id=problem.id,
                occurrence_number=problem.occurrence_number + 1,
            )
            target.problem_list.add(occurrence)
            existing_lineages.add(problem.lineage_id)
            created.append(occurrence)
        return tuple(created)


class ProblemService(ServiceBase):
    """Coordinate ordered problem mutations through the patient aggregate."""

    def list(self, patient_id: UUID, day_id: UUID) -> tuple[Problem, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return self._day(self._patient(unit_of_work, patient_id), day_id).problem_list.problems

    def add(
        self,
        patient_id: UUID,
        day_id: UUID,
        *,
        title: str,
        description: str = "",
        priority: ClinicalPriority = ClinicalPriority.ROUTINE,
        assessment: str = "",
        plan: str = "",
        notes: str = "",
    ) -> Problem:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                problem_list = self._day(patient, day_id).problem_list
                problem = Problem(
                    patient_id,
                    day_id,
                    title,
                    description=description,
                    priority=priority,
                    assessment=assessment,
                    plan=plan,
                    notes=notes,
                    ordering_position=len(problem_list.problems),
                )
                problem_list.add(problem)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(problem.id), "created"))
        return problem

    def update(
        self,
        patient_id: UUID,
        day_id: UUID,
        problem_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: ClinicalPriority | None = None,
    ) -> Problem:
        return self._mutate(
            patient_id,
            day_id,
            problem_id,
            "updated",
            lambda problem: problem.update_details(
                title=title, description=description, priority=priority
            ),
        )

    def update_from(
        self,
        patient_id: UUID,
        day_id: UUID,
        problem_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: ClinicalPriority | None = None,
        assessment: str | None = None,
        plan: str | None = None,
        notes: str | None = None,
    ) -> tuple[Problem, ...]:
        """Edit matching lineage occurrences from the selected day forward."""
        return self._mutate_forward(
            patient_id,
            day_id,
            problem_id,
            "updated_forward",
            lambda problem: problem.update_details(
                title=title,
                description=description,
                priority=priority,
                assessment=assessment,
                plan=plan,
                notes=notes,
            ),
            lambda _problem: True,
        )

    def change_status(
        self,
        patient_id: UUID,
        day_id: UUID,
        problem_id: UUID,
        status: ProblemStatus,
        changed_at: datetime | None = None,
    ) -> Problem:
        return self._mutate(
            patient_id,
            day_id,
            problem_id,
            f"status:{status.value}",
            lambda problem: problem.change_status(status, changed_at),
        )

    def change_status_from(
        self,
        patient_id: UUID,
        day_id: UUID,
        problem_id: UUID,
        status: ProblemStatus,
        changed_at: datetime | None = None,
    ) -> tuple[Problem, ...]:
        """Apply a lifecycle change to this and later eligible lineage occurrences."""

        def eligible(problem: Problem) -> bool:
            if status is ProblemStatus.RESOLVED:
                return problem.status not in {
                    ProblemStatus.RESOLVED,
                    ProblemStatus.INACTIVE,
                }
            if status is ProblemStatus.ACTIVE:
                return problem.status is not ProblemStatus.ACTIVE
            return problem.status not in {
                status,
                ProblemStatus.RESOLVED,
                ProblemStatus.INACTIVE,
            }

        return self._mutate_forward(
            patient_id,
            day_id,
            problem_id,
            f"status_forward:{status.value}",
            lambda problem: problem.change_status(status, changed_at),
            eligible,
        )

    def reorder(self, patient_id: UUID, day_id: UUID, ordered_ids: Sequence[UUID]) -> None:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                self._day(patient, day_id).problem_list.reorder(list(ordered_ids))
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(day_id), "reordered"))

    def replace_titles_from(
        self,
        patient_id: UUID,
        day_id: UUID,
        titles: Sequence[str],
    ) -> tuple[Problem, ...]:
        """Compatibility wrapper for callers that provide titles without supporting details."""
        return self.replace_entries_from(
            patient_id,
            day_id,
            tuple(ProblemListEntry(title) for title in titles),
        )

    def replace_entries_from(
        self,
        patient_id: UUID,
        day_id: UUID,
        entries: Sequence[ProblemListEntry],
    ) -> tuple[Problem, ...]:
        """Reconcile ordered titles/details forward while preserving problem identities."""
        normalized = tuple(
            ProblemListEntry(entry.title.strip(), entry.description.strip())
            for entry in entries
            if entry.title.strip()
        )
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                selected_day = self._day(patient, day_id)
                existing = list(selected_day.problem_list.problems)
                retained: list[Problem] = []
                unused = list(existing)
                for entry in normalized:
                    selected = next(
                        (problem for problem in unused if problem.title == entry.title),
                        None,
                    )
                    if selected is None and unused:
                        selected = unused[0]
                    if selected is None:
                        created = Problem(
                            patient_id,
                            day_id,
                            entry.title,
                            description=entry.description,
                            ordering_position=len(retained),
                        )
                        selected_day.problem_list.add(created)
                        retained.append(created)
                        source = created
                        for later_day in patient.hospital_days:
                            if later_day.day_number <= selected_day.day_number:
                                continue
                            occurrence = Problem(
                                patient_id,
                                later_day.id,
                                entry.title,
                                description=entry.description,
                                ordering_position=len(later_day.problem_list.problems),
                                lineage_id=created.lineage_id,
                                source_problem_id=source.id,
                                occurrence_number=source.occurrence_number + 1,
                            )
                            later_day.problem_list.add(occurrence)
                            source = occurrence
                        continue
                    unused.remove(selected)
                    for day in patient.hospital_days:
                        if day.day_number < selected_day.day_number:
                            continue
                        for problem in day.problem_list.problems:
                            if problem.lineage_id == selected.lineage_id:
                                problem.update_details(
                                    title=entry.title,
                                    description=entry.description,
                                )
                    retained.append(selected)
                omitted = {problem.lineage_id for problem in unused}
                if omitted:
                    for day in patient.hospital_days:
                        if day.day_number < selected_day.day_number:
                            continue
                        for problem in tuple(day.problem_list.problems):
                            if problem.lineage_id in omitted:
                                day.problem_list.remove(problem.id)
                selected_day.problem_list.reorder([problem.id for problem in retained])
                ordered_lineages = [problem.lineage_id for problem in retained]
                for later_day in patient.hospital_days:
                    if later_day.day_number <= selected_day.day_number:
                        continue
                    by_lineage = {
                        problem.lineage_id: problem for problem in later_day.problem_list.problems
                    }
                    ordered = [
                        by_lineage[lineage] for lineage in ordered_lineages if lineage in by_lineage
                    ]
                    ordered.extend(
                        problem
                        for problem in later_day.problem_list.problems
                        if problem.lineage_id not in ordered_lineages
                    )
                    later_day.problem_list.reorder([problem.id for problem in ordered])
                # SOAP documents retain explicit problem IDs. Reconcile those references
                # in the same aggregate save so a line deletion cannot leave a dangling
                # foreign key before the Markdown projection refreshes.
                for day in patient.hospital_days:
                    if day.day_number < selected_day.day_number:
                        continue
                    active_ids = tuple(problem.id for problem in day.problem_list.active_problems)
                    for document in day.soap_documents:
                        document.set_problem_references(active_ids)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(day_id), "list_replaced_forward"))
        return tuple(retained)

    def remove(self, patient_id: UUID, day_id: UUID, problem_id: UUID) -> Problem:
        removed: Problem
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                removed = self._day(patient, day_id).problem_list.remove(problem_id)
                unit_of_work.patients.save(patient)
        except EntityNotFoundError as error:
            raise ResourceNotFoundError(f"Problem {problem_id} was not found.") from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(problem_id), "removed"))
        return removed

    def remove_from(self, patient_id: UUID, day_id: UUID, problem_id: UUID) -> tuple[Problem, ...]:
        """Remove this and later occurrences while retaining earlier history."""
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                selected_day = self._day(patient, day_id)
                try:
                    selected = selected_day.problem_list.get(problem_id)
                except EntityNotFoundError as error:
                    raise ResourceNotFoundError(f"Problem {problem_id} was not found.") from error
                removed: list[Problem] = []
                for day in patient.hospital_days:
                    if day.day_number < selected_day.day_number:
                        continue
                    for problem in tuple(day.problem_list.problems):
                        if problem.lineage_id == selected.lineage_id:
                            removed.append(day.problem_list.remove(problem.id))
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(selected.lineage_id), "removed_forward"))
        return tuple(removed)

    def _mutate(
        self,
        patient_id: UUID,
        day_id: UUID,
        problem_id: UUID,
        operation: str,
        action: Callable[[Problem], None],
    ) -> Problem:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                try:
                    problem = self._day(patient, day_id).problem_list.get(problem_id)
                except EntityNotFoundError as error:
                    raise ResourceNotFoundError(f"Problem {problem_id} was not found.") from error
                action(problem)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(problem_id), operation))
        return problem

    def _mutate_forward(
        self,
        patient_id: UUID,
        day_id: UUID,
        problem_id: UUID,
        operation: str,
        action: Callable[[Problem], None],
        eligible: Callable[[Problem], bool],
    ) -> tuple[Problem, ...]:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                selected_day = self._day(patient, day_id)
                try:
                    selected = selected_day.problem_list.get(problem_id)
                except EntityNotFoundError as error:
                    raise ResourceNotFoundError(f"Problem {problem_id} was not found.") from error
                affected = tuple(
                    problem
                    for day in patient.hospital_days
                    if day.day_number >= selected_day.day_number
                    for problem in day.problem_list.problems
                    if problem.lineage_id == selected.lineage_id and eligible(problem)
                )
                if not affected:
                    raise InvalidOperationError("No eligible problem occurrences were found.")
                for problem in affected:
                    action(problem)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ProblemChanged(str(selected.lineage_id), operation))
        return affected
