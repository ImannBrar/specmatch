"""Application error types."""


class DependencyError(Exception):
    """Raised when a call to an external dependency fails.

    See CONTRIBUTING.md — external-dependency failures must be caught at the
    call site, logged as a structured `dependency_failure` event, and
    re-raised as this type with `raise ... from exc`.
    """


class MatchNotFoundError(LookupError):
    """Raised when no persisted match exists for a record id."""


class InvalidReviewError(ValueError):
    """Raised when a review request is inconsistent (e.g. an override
    without a catalog_id, or one that names an unknown catalog entry)."""
