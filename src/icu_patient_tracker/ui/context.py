"""Single presentation-context source of truth."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class PresentationContext:
    """Own transient selection and operation state without owning clinical data."""

    patient_id: UUID | None = None
    hospital_day_id: UUID | None = None
    workspace: str = "charting"
    search_text: str = ""
    sort_mode: str = "manual"
    is_dirty: bool = False
    is_loading: bool = False
    save_status: str = "Saved"
    generation: int = 0

    def select_patient(self, patient_id: UUID | None) -> None:
        self.patient_id = patient_id
        self.hospital_day_id = None
        self.generation += 1

    def select_day(self, day_id: UUID | None) -> None:
        self.hospital_day_id = day_id
        self.generation += 1
