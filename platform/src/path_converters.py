"""
AgentX Platform — Custom Starlette path converters
══════════════════════════════════════════════════════
Registers URL path converters that fix two routing issues in FastAPI:

1. **UUID vs DID collision.** Several endpoints define `/{agent_id}` with
   `agent_id: UUID` type. FastAPI matches path first, validates type second,
   so a DID like `did:agentx:alice-335` matches the path but fails UUID
   parsing with a 422 — instead of falling through to the `{agent_did}`
   route.

2. **:path greedy match.** The `:path` converter matches across `/`, so
   `/agents/{agent_did:path}` defined BEFORE `/agents/{agent_did}/followers`
   (registered in a different router) swallows the `/followers` suffix and
   returns a spurious 404.

Both problems disappear when DID-typed routes use a custom converter that:
  - requires the segment to start with `did:`
  - refuses to cross `/`

A DID string will only match `{agent_did:did}`; a UUID string won't match
it at all and will fall through to the UUID-typed route naturally.

Usage:
    # At module import time (main.py before routers register):
    from .path_converters import register_did_converter
    register_did_converter()

    # In router definitions:
    @router.get("/{agent_did:did}")
    @router.get("/{agent_did:did}/followers")
"""
from starlette.convertors import Convertor, register_url_convertor


class DIDConvertor(Convertor):
    """
    Matches AgentX DID strings: `did:<method>:<identifier>`.

    The regex allows:
      - ASCII letters, digits, hyphens, underscores, dots, colons
      - URL-encoded characters (`%NN`)
    It disallows slashes so `/followers`, `/trust`, etc. remain routable
    as their own path segments.
    """
    regex = r"did:[A-Za-z0-9._%:\-]+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


_registered = False


def register_did_converter() -> None:
    """Register the `did` URL convertor. Idempotent — safe to call more than once."""
    global _registered
    if _registered:
        return
    register_url_convertor("did", DIDConvertor())
    _registered = True
