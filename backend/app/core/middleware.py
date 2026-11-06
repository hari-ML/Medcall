"""Request context: correlation IDs + request logging.

Every request gets an ``X-Request-ID`` (client-supplied or generated) that is
returned as a response header and stamped on the access log line — the hook
Phase 2+ audit logging hangs off.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: Current request's correlation id (None outside a request context).
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

_logger = logging.getLogger("medrecall.request")


def current_request_id() -> str | None:
    return request_id_ctx.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign X-Request-ID, log method/path/status/duration for every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = (request.headers.get("X-Request-ID") or "").strip() or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            _logger.info(
                "%s %s -> %s (%.0f ms) rid=%s",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                rid,
            )
            request_id_ctx.reset(token)
