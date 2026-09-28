"""Stable application-service failures suitable for presentation by any UI."""


class ApplicationServiceError(Exception):
    """Base failure exposed by the application layer."""


class ResourceNotFoundError(ApplicationServiceError, LookupError):
    """A requested application resource was not found."""


class PatientNotFoundError(ResourceNotFoundError):
    """A patient aggregate was not found."""


class HospitalDayNotFoundError(ResourceNotFoundError):
    """A hospital day was not found."""


class TaskNotFoundError(ResourceNotFoundError):
    """A task occurrence was not found."""


class SOAPDocumentNotFoundError(ResourceNotFoundError):
    """A SOAP document was not found."""


class InvalidOperationError(ApplicationServiceError):
    """The requested use case violates an application or domain rule."""


class DuplicateHospitalDayError(InvalidOperationError):
    """A patient already has a day on the requested calendar date."""


class SettingsValidationError(ApplicationServiceError, ValueError):
    """Device-local settings are invalid."""


class ApplicationPersistenceError(ApplicationServiceError):
    """A persistence operation failed without leaking backend details."""


class AutosaveServiceError(ApplicationServiceError):
    """A coordinated autosave failed."""


class BackupServiceError(ApplicationServiceError):
    """A coordinated backup or restore failed."""


class ClipboardServiceError(ApplicationServiceError):
    """A safe clipboard export could not be completed."""


class RecoveryServiceError(ApplicationServiceError):
    """A recovery snapshot could not be staged, loaded, or cleared."""
