"""Error envelope helpers."""
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder


async def http_error_handler(request: Request, exc) -> JSONResponse:
    status = int(getattr(exc, "status_code", 500))
    detail = getattr(exc, "detail", "unexpected error")
    if isinstance(detail, dict):
        code = detail.get("code", "INTERNAL_ERROR")
        message = detail.get("message", str(detail))
        extra = detail.get("details", {})
    elif status >= 500:
        code, message, extra = "INTERNAL_ERROR", "unexpected server error", {}
    else:
        code = {401: "UNAUTHORIZED", 404: "NODE_NOT_FOUND", 422: "VALIDATION_ERROR", 502: "UPSTREAM_UNAVAILABLE"}.get(status, "INTERNAL_ERROR")
        message = str(detail)
        extra = {}
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
        "details": jsonable_encoder(extra), "request_id": getattr(request.state, "request_id", request.headers.get("X-Request-Id"))}})


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR",
        "message": "request body or query does not match the contract",
        "details": {"errors": jsonable_encoder(exc.errors())},
        "request_id": getattr(request.state, "request_id", request.headers.get("X-Request-Id"))}})
