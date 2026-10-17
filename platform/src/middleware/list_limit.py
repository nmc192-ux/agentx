"""
AgentX Platform — List size cap
════════════════════════════════
Pure ASGI middleware: any ``limit`` query parameter above ``max_limit`` is
rewritten to ``max_limit`` before the request reaches a router.

Why (EG-1, Neon egress, Oct 2026): the Neon free plan was suspended on
11 Oct after 7.3 GB of transfer against a 5 GB allowance. Many list routes
accepted ``limit`` up to 100, 200 or 500, and every row a route returns is a
row read out of Neon. Capping at the edge covers every route at once,
including ones added later, without each router having to remember.

Clamping instead of rejecting keeps older SDKs and UIs that send
``limit=100`` or ``limit=200`` working: they get the first 50 and page on
(the response's own ``limit`` / ``has_more`` / cursor fields reflect the
clamped value because the router only ever sees 50).

Values that are not whole numbers, or are 50 or below, are left alone so the
router's own validation still answers them (422 for ``limit=abc``,
``limit=0``). Non-HTTP scopes pass through untouched.
"""
from urllib.parse import parse_qsl, urlencode

MAX_LIST_LIMIT = 50


class ListLimitMiddleware:
    def __init__(self, app, max_limit: int = MAX_LIST_LIMIT):
        self.app = app
        self.max_limit = max_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            qs = scope.get("query_string", b"")
            if b"limit=" in qs:
                new_qs = self._clamp(qs)
                if new_qs is not None:
                    scope = dict(scope, query_string=new_qs)
        await self.app(scope, receive, send)

    def _clamp(self, qs: bytes) -> bytes | None:
        try:
            pairs = parse_qsl(qs.decode("latin-1"), keep_blank_values=True)
        except ValueError:
            return None
        changed = False
        out = []
        for key, value in pairs:
            if key == "limit":
                try:
                    if int(value) > self.max_limit:
                        value = str(self.max_limit)
                        changed = True
                except ValueError:
                    pass
            out.append((key, value))
        if not changed:
            return None
        return urlencode(out).encode("latin-1")
