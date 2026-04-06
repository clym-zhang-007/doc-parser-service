"""全局异常处理器：统一 `{"error": {"code", "message"}}` 响应。"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    """在应用上注册处理器（顺序：细粒度先于通用 Exception）。"""

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=_envelope(str(detail["code"]), str(detail["message"])),
            )
        if isinstance(detail, str):
            code = _default_code_for_status(exc.status_code)
            return JSONResponse(
                status_code=exc.status_code,
                content=_envelope(code, detail),
            )
        code = _default_code_for_status(exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        parts: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            parts.append(f"{loc}: {err.get('msg', '')}")
        message = "; ".join(parts) if parts else "request validation failed"
        return JSONResponse(
            status_code=422,
            content=_envelope(ErrorCode.VALIDATION_ERROR, message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                ErrorCode.INTERNAL_ERROR,
                "An unexpected error occurred",
            ),
        )


def _default_code_for_status(status: int) -> str:
    if status == 404:
        return ErrorCode.JOB_NOT_FOUND
    if status == 413:
        return ErrorCode.FILE_TOO_LARGE
    if status == 415:
        return ErrorCode.UNSUPPORTED_FILE_TYPE
    if status == 422:
        return ErrorCode.VALIDATION_ERROR
    if status >= 500:
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.INTERNAL_ERROR
