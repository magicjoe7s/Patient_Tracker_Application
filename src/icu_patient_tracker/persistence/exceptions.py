"""Public persistence failures that hide database implementation details."""


class PersistenceError(Exception):
    """Base class for errors raised by persistence infrastructure."""


class RecordNotFoundError(PersistenceError, LookupError):
    """A requested aggregate does not exist."""


class DuplicateIdentityError(PersistenceError):
    """A stable identifier conflicts with an existing record."""


class ConstraintViolationError(PersistenceError):
    """Stored data would violate a database integrity constraint."""


class TransactionError(PersistenceError):
    """An atomic persistence operation failed and was rolled back."""


class MigrationError(PersistenceError):
    """A formal schema migration could not be completed."""


class UnsupportedSchemaVersionError(MigrationError):
    """The database reports a schema revision unknown to this application."""


class BackupError(PersistenceError):
    """A consistent and verifiable backup could not be created."""


class RestoreError(PersistenceError):
    """A candidate backup could not safely replace the active database."""


class AutosaveError(PersistenceError):
    """A scheduled or explicit autosave operation failed."""


class RecoveryError(PersistenceError):
    """A local unsaved-editor recovery snapshot could not be handled safely."""
