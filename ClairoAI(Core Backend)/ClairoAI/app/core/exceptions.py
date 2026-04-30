"""
Custom exceptions and global FastAPI exception handlers.

Each exception maps to a consistent, human-readable JSON error response.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.core.logging import get_logger

logger = get_logger("exceptions")


# ── Custom Exceptions ────────────────────────────────────────────


class ContextBridgeError(Exception):
    """Base exception for all ContextBridge errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class InputValidationError(ContextBridgeError):
    """Raised when input data fails validation."""

    def __init__(self, message: str = "Invalid input provided"):
        super().__init__(message=message, status_code=422)


class LLMError(ContextBridgeError):
    """Raised when the LLM service fails."""

    def __init__(self, message: str = "LLM service encountered an error"):
        super().__init__(message=message, status_code=502)


class JobNotFoundError(ContextBridgeError):
    """Raised when a requested job does not exist."""

    def __init__(self, job_id: str):
        super().__init__(
            message=f"Job '{job_id}' not found",
            status_code=404,
        )


class FileProcessingError(ContextBridgeError):
    """Raised when file upload or extraction fails."""

    def __init__(self, message: str = "File processing failed"):
        super().__init__(message=message, status_code=400)


class RAGUnavailableError(ContextBridgeError):
    """Raised when the RAG service is unreachable (non-fatal)."""

    def __init__(self, message: str = "RAG service is currently unavailable"):
        super().__init__(message=message, status_code=503)


def _error_payload(message: str, details: str | None = None) -> dict:
    payload = {
        "ok": False,
        "error": str(message),
    }
    if details:
        payload["details"] = str(details)
    return payload


def _extract_http_exception_message(exc: HTTPException) -> tuple[str, str | None]:
    detail = exc.detail

    if isinstance(detail, dict):
        message = detail.get("error") or detail.get("message") or "Something went wrong"
        details = detail.get("details") or detail.get("suggestion")
        return str(message), str(details) if details else None

    if isinstance(detail, list):
        combined = "; ".join(str(item) for item in detail if item)
        return (combined or "Request validation failed"), None

    if detail:
        return str(detail), None

    return "Something went wrong", None


# ── Global Exception Handlers ───────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(ContextBridgeError)
    async def contextbridge_error_handler(
        request: Request, exc: ContextBridgeError
    ) -> JSONResponse:
        logger.error(
            f"{exc.__class__.__name__}: {exc.message}",
            extra={"extra_data": {"path": str(request.url)}},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.message, details=exc.__class__.__name__),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        message, details = _extract_http_exception_message(exc)
        logger.error(
            f"HTTPException: {message}",
            extra={"extra_data": {"path": str(request.url), "status_code": exc.status_code, "details": details}},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(message, details=details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(part) for part in err.get('loc', []))}: {err.get('msg', '')}"
            for err in exc.errors()
        )
        message = "Invalid request. Please review the submitted input."
        logger.error(
            f"RequestValidationError: {details}",
            extra={"extra_data": {"path": str(request.url)}},
        )
        return JSONResponse(
            status_code=422,
            content=_error_payload(message, details=details),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            f"Unhandled exception: {exc}",
            extra={"extra_data": {"path": str(request.url)}},
        )
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "Something went wrong on our side.",
                details=exc.__class__.__name__,
            ),
        )
