"""Logging: JSON lines with a per-request correlation id, and redaction of secrets.

Every log record gets ``request_id`` from a context variable set by RequestIdMiddleware, so one id ties
together the API request, gateway metering, worker logs (the id travels in tunnel frames), and audit rows.
Prompts and responses are never logged; credentials are redacted even if a caller logs them by mistake.
"""

import contextvars
import json
import logging
import re
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
client_ip_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_ip", default=None)

_SECRET_PATTERNS = [
    re.compile(r"\b(am_(?:sk|node|enroll)_)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b((?:sk|pk)_(?:test|live)_)[A-Za-z0-9]{8,}"),  # Paystack keys
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(\"?(?:password|secret|token|credential|api_key)\"?\s*[:=]\s*\"?)[^\s\",}]{4,}"),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text


def current_request_id() -> str | None:
    return request_id_var.get()


def new_request_id() -> str:
    return uuid.uuid4().hex


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry)


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Access logs include full URLs and are noisy; errors still surface through the app's own logging.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestIdMiddleware:
    """Assign a server-generated correlation id to each request and return it as X-Request-ID.

    Incoming X-Request-ID headers are deliberately not adopted: the id doubles as the metering key, and a
    client-chosen id could be replayed to suppress usage records."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        rid = new_request_id()
        token = request_id_var.set(rid)
        client = scope.get("client")
        ip_token = client_ip_var.set(client[0] if client else None)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers = [(k, v) for k, v in headers if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
            client_ip_var.reset(ip_token)
