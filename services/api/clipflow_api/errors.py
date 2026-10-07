"""Structured errors: {"code", "message", "request_id", "details"?} (PRD §E)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found() -> ApiError:
    # Cross-tenant access is answered exactly like a missing resource (architecture §2.2 rule 5).
    return ApiError(404, "NOT_FOUND", "ไม่พบรายการนี้")


def _body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    body = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}
    if details:
        body["details"] = details
    return body


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # Field names and reasons only; submitted values (e.g. passwords) are never echoed.
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "reason": e["type"]} for e in exc.errors()]
        return JSONResponse(_body(request, "VALIDATION_ERROR", "ข้อมูลไม่ถูกต้อง", {"fields": fields}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code)
