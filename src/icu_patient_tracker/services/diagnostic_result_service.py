"""Record results against canonical pending-diagnostic tasks."""

from __future__ import annotations

from uuid import UUID

from icu_patient_tracker.domain.diagnostic_result import DiagnosticResult
from icu_patient_tracker.domain.enums import TaskCategory, TaskStatus
from icu_patient_tracker.domain.exceptions import DomainError
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase
from icu_patient_tracker.services.events import TaskChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError


class DiagnosticResultService(ServiceBase):
    """Create or update one lossless result and optionally complete its task."""

    def record(
        self,
        patient_id: UUID,
        day_id: UUID,
        task_id: UUID,
        result_text: str,
        *,
        complete: bool = False,
    ) -> Task:
        task: Task
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                task = next((item for item in day.tasks if item.id == task_id), None)  # type: ignore[assignment]
                if task is None:
                    raise InvalidOperationError(
                        "The selected diagnostic was not found on this day."
                    )
                if task.category is not TaskCategory.DIAGNOSTIC:
                    raise InvalidOperationError("Results can only be linked to diagnostic tasks.")
                if task.status is TaskStatus.CANCELLED:
                    raise InvalidOperationError("A cancelled diagnostic cannot receive a result.")
                if task.diagnostic_result is None:
                    task.attach_diagnostic_result(
                        DiagnosticResult(patient_id, day_id, task.id, result_text)
                    )
                else:
                    task.diagnostic_result.update(result_text)
                if complete and task.status is not TaskStatus.COMPLETED:
                    task.complete()
                unit_of_work.patients.save(patient)
        except InvalidOperationError:
            raise
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        operation = "diagnostic_result_completed" if complete else "diagnostic_result_recorded"
        self._publisher.publish(TaskChanged(str(task.id), operation))
        return task
