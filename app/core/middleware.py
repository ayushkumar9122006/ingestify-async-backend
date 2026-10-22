import uuid
import logging
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable to store correlation ID per asynchronous request context
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id_ctx", default="")


def get_correlation_id() -> str:
    """Retrieve active correlation ID from context or generate a fallback trace ID."""
    cid = correlation_id_ctx.get()
    return cid if cid else str(uuid.uuid4())


class CorrelationIdFilter(logging.Filter):
    """Logging filter that injects correlation_id into all logging records."""
    def filter(self, record: logging.LogRecord) -> bool:
        cid = correlation_id_ctx.get()
        record.correlation_id = cid if cid else "-"
        return True


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that captures incoming X-Request-ID or generates a new UUID4.
    Attaches the correlation ID to the response header and request context.
    """
    HEADER_NAME = "X-Request-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check incoming headers for X-Request-ID
        req_id = request.headers.get(self.HEADER_NAME) or request.headers.get("x-request-id")
        if not req_id:
            req_id = str(uuid.uuid4())

        # Set context variable for downstream handlers, loggers, and services
        token = correlation_id_ctx.set(req_id)
        # Store in request state for easy access in endpoints
        request.state.correlation_id = req_id

        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = req_id
            return response
        finally:
            correlation_id_ctx.reset(token)
