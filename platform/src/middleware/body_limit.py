"""
AgentX Platform — Request body size limit
══════════════════════════════════════════
Pure ASGI middleware: rejects POST/PUT/PATCH bodies over ``max_bytes`` with 413.

Sprint 9 (S9-8a2): the old check only read ``Content-Length``, so a chunked
upload (no ``Content-Length``) went straight through at any size. This counts
the bytes actually received:

  - ``Content-Length`` present and over the limit → 413 before reading anything
  - ``Content-Length`` not a whole number → 400
  - otherwise the body is read up to ``max_bytes + 1`` bytes; over → 413,
    else the buffered body is replayed to the app unchanged

Buffering is bounded by ``max_bytes`` (64 KiB in main.py), so it is cheap.
Non-HTTP scopes (websocket, lifespan) pass through untouched.
"""
import json

_CHECKED_METHODS = frozenset({"POST", "PUT", "PATCH"})


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _CHECKED_METHODS:
            await self.app(scope, receive, send)
            return

        too_large = {"detail": "Request body too large", "max_bytes": self.max_bytes}

        content_length = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                content_length = value
                break
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await _send_json(send, 400, {"detail": "Invalid Content-Length header"})
                return
            if declared > self.max_bytes:
                await _send_json(send, 413, too_large)
                return

        # Read the body ourselves, counting real bytes (covers chunked uploads
        # and a Content-Length that understates the body).
        messages = []
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                messages.append(message)
                break
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await _send_json(send, 413, too_large)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)
