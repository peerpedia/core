# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

r"""Semantic exceptions — pure business logic, no IO concepts.

Exception hierarchy
-------------------
PeerpediaError (base)       ``code: str``  ``detail: str``  ``context: dict``
  ├── NotFoundError          resource_type, resource_id
  ├── NotAuthorizedError     permission, resource_type, resource_id
  ├── ConflictError          conflicting_entity
  └── BadRequestError        field, bad_value
"""


class PeerpediaError(Exception):
    """Base for all PeerPedia business-logic errors.

    Attributes:
        detail: Human-readable description (always present).
        code:  Machine-readable error code (default ``"ERROR"``).
        context:  Arbitrary key-value pairs for structured error output.
    """

    code: str = "ERROR"

    def __init__(self, detail: str = "", **context):
        if "code" in context:
            self.code = context.pop("code")
        if not detail and self.code != "ERROR":
            detail = self.code
        super().__init__(detail)
        self.detail = detail
        self.context = context
        for k, v in context.items():
            setattr(self, k, v)


class NotFoundError(PeerpediaError):
    """Requested resource does not exist."""

    code = "NOT_FOUND"

    def __init__(self, detail: str = "", resource_type: str = "", resource_id: str = "", **kwargs):
        if resource_type and resource_id:
            kwargs[f"{resource_type}_id"] = resource_id
        super().__init__(detail, resource_type=resource_type, resource_id=resource_id, **kwargs)


class NotAuthorizedError(PeerpediaError):
    """User lacks permission for the requested action."""

    code = "NOT_AUTHORIZED"

    def __init__(self, detail: str = "", permission: str = "",
                 resource_type: str = "", resource_id: str = "", **kwargs):
        super().__init__(detail, permission=permission,
                         resource_type=resource_type, resource_id=resource_id, **kwargs)


class ConflictError(PeerpediaError):
    """Request conflicts with the current state of the resource."""

    code = "CONFLICT"

    def __init__(self, detail: str = "", conflicting_entity: str = "", **kwargs):
        super().__init__(detail, conflicting_entity=conflicting_entity, **kwargs)


class BadRequestError(PeerpediaError):
    """Input is invalid or missing required data."""

    code = "BAD_REQUEST"

    def __init__(self, detail: str = "", field: str = "", bad_value: str = "", **kwargs):
        super().__init__(detail, field=field, bad_value=bad_value, **kwargs)


class MergeConflictError(ConflictError):
    """Raised when a merge encounters conflicts that can't auto-resolve.

    Storage-layer concept — git-specific in the current backend,
    but the concept applies to any versioned storage.
    """

    code = "MERGE_CONFLICT"

    def __init__(self, detail: str = "", conflicting_entity: str = "", **kwargs):
        super().__init__(detail, conflicting_entity=conflicting_entity, **kwargs)
