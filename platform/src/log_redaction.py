"""AgentX Platform — keep bearer tokens out of the process log.

The WebSocket endpoint takes the access token as ``?token=`` because browser
WebSocket clients cannot send an ``Authorization`` header. uvicorn prints the
request line *with* the query string: ``"WebSocket /ws?token=eyJ..." [accepted]``
on its ``uvicorn.error`` logger and HTTP lines on ``uvicorn.access``. Left alone,
every live access token would sit in the container log (Fly's log drain today,
``docker compose logs`` on the VPS, Caddy's shared container next door).

``install()`` attaches :class:`RedactQueryTokenFilter` to those loggers. A logging
filter runs on the logger the record is created on, before it propagates, so the
handlers (and anything reading the log) only ever see ``token=REDACTED``.

Found in the Sprint 16 security review (S16-6); pinned by
``tests/infrastructure/test_vps_deploy_files.py``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

# `token=<value>` inside a URL or query string, whatever the case of the name (also
# refresh_token=, access_token=: anything that ends in token=).
# The value runs to the next `&`, whitespace or quote.
_TOKEN_QUERY = re.compile(r"(?i)(token=)[^&\s\"']+")
REDACTED = "REDACTED"

# Loggers uvicorn writes request lines to (websockets_impl -> uvicorn.error).
UVICORN_LOGGERS = ("uvicorn.error", "uvicorn.access")


def redact(value: Any) -> Any:
    """Return ``value`` with every ``token=...`` query value replaced."""
    if isinstance(value, str) and "token=" in value.lower():
        return _TOKEN_QUERY.sub(rf"\g<1>{REDACTED}", value)
    return value


class RedactQueryTokenFilter(logging.Filter):
    """Scrub ``token=`` query values from a record's message and arguments.

    Never drops a record (always returns True); it only rewrites it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: redact(v) for k, v in args.items()}
        else:
            record.args = redact(args)
        return True


def install(names: tuple[str, ...] = UVICORN_LOGGERS) -> None:
    """Attach the filter once to each named logger (idempotent)."""
    for name in names:
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactQueryTokenFilter) for f in target.filters):
            target.addFilter(RedactQueryTokenFilter())
