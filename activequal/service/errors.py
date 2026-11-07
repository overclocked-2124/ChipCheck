"""Backend errors, mapped one-to-one onto the HTTP error model of HLD 05 §4.1."""

from __future__ import annotations

from typing import Any

HTTP_STATUS = {
    "INVALID_ARGUMENT": 400,
    "UNAUTHENTICATED": 401,
    "PERMISSION_DENIED": 403,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "STALE_VERSION": 409,
    "IDEMPOTENCY_MISMATCH": 409,
    "INTEGRITY_ERROR": 409,
    "FAILED_PRECONDITION": 412,
    "UNAVAILABLE": 503,
}


class BackendError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        if code not in HTTP_STATUS:
            raise ValueError(f"unknown error code {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def status(self) -> int:
        return HTTP_STATUS[self.code]

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def invalid(message: str, **details: Any) -> BackendError:
    return BackendError("INVALID_ARGUMENT", message, details)


def not_found(what: str) -> BackendError:
    return BackendError("NOT_FOUND", f"{what} not found")


def precondition(message: str, **details: Any) -> BackendError:
    return BackendError("FAILED_PRECONDITION", message, details)
