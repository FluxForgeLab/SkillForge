"""Unified API error responses and exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from skillforge.domain.errors import InvalidStateTransition, SkillForgeError

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def _error_response(
    status_code: int,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, str):
            message = detail
            details = None
        elif isinstance(detail, dict):
            message = str(detail.get("message", detail))
            details = detail
        else:
            message = str(detail)
            details = None
        return _error_response(
            exc.status_code,
            code="http_error",
            message=message,
            details=details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            422,
            code="validation_error",
            message="Request validation failed",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(InvalidStateTransition)
    async def invalid_transition_handler(
        _request: Request,
        exc: InvalidStateTransition,
    ) -> JSONResponse:
        return _error_response(
            409,
            code="invalid_state_transition",
            message=str(exc),
            details={
                "machine": exc.machine,
                "current": exc.current,
                "target": exc.target,
            },
        )

    @app.exception_handler(SkillForgeError)
    async def skillforge_error_handler(_request: Request, exc: SkillForgeError) -> JSONResponse:
        return _error_response(400, code="skillforge_error", message=str(exc))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return _error_response(500, code="internal_error", message="Internal server error")
