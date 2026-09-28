"""Explicit failures raised when clinical domain rules are violated."""


class DomainError(Exception):
    """Base class for errors caused by invalid domain operations."""


class DomainValidationError(DomainError, ValueError):
    """A model was given a value that cannot represent valid clinical state."""


class DuplicateEntityError(DomainError):
    """A collection already contains the supplied entity identifier."""


class EntityNotFoundError(DomainError, LookupError):
    """A requested entity does not belong to the target collection."""


class InvalidStateTransitionError(DomainError):
    """An entity cannot move directly between the requested states."""


class RelationshipError(DomainError):
    """Related entities do not share the required owner or context."""


class FinalizedDocumentError(DomainError):
    """An operation attempted to alter an immutable clinical document."""
