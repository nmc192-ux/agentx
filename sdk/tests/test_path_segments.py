"""
agentx_sdk — ids interpolated into request paths (``_seg``).

Starlette decodes ``%2F`` before routing, so an id containing a slash could
choose a different route (``posts.get("abc/replies")`` → ``GET /posts/abc/replies``).
Every id that goes into a path passes through ``_seg``, which refuses such an
id with ``ValueError`` *before* any request is sent and percent-encodes the
rest. One method per namespace is exercised, plus a source scan proving no
f-string path interpolates a raw value.
"""
import asyncio
import pathlib
import re
from uuid import UUID

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentIdentity, AgentXClient
from agentx_sdk._paths import _seg


BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
UUID_ID = "11111111-1111-1111-1111-111111111111"

BAD_IDS = ["abc/replies", "../x", "a/../b", "/", "", ".", "..", "a\\b"]


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


# One call per namespace / client area that puts a caller-supplied id in a path.
CALLS = {
    "posts.get":                 lambda c, i: c.posts.get(i),
    "posts.reply":               lambda c, i: c.posts.reply(i, "t", "hi"),
    "collectives.join":          lambda c, i: c.collectives.join(i),
    "collectives.approve":       lambda c, i: c.collectives.approve(UUID_ID, i),
    "communities.join":          lambda c, i: c.communities.join(i),
    "memory.load":               lambda c, i: c.memory.load(i),
    "memory.save":               lambda c, i: c.memory.save(i, 1),
    "capabilities.remove":      lambda c, i: c.capabilities.remove_from_agent(i),
    "notifications.mark_read":   lambda c, i: c.notifications.mark_read(i),
    "social.follow":             lambda c, i: c.social.follow(i),
    "contracts.complete":        lambda c, i: c.contracts.complete(i),
    "verification.get":          lambda c, i: c.verification.get(i),
    "wallet.release_stake":      lambda c, i: c.wallet.release_stake(i),
    "a2a.get_my_card":           lambda c, i: (
        setattr(c.identity, "agent_did", i), c.a2a.get_my_card()),
    "client.get_agent":          lambda c, i: c.get_agent(i),
    "client.approve_task_result": lambda c, i: c.approve_task_result(i),
    "client.get_bounty":         lambda c, i: c.get_bounty(i),
}


# -- _seg itself ----------------------------------------------------------------

class TestSeg:
    @pytest.mark.parametrize("bad", BAD_IDS + [None, True])
    def test_refuses(self, bad):
        with pytest.raises(ValueError):
            _seg(bad)

    def test_percent_encoded_slash_stays_one_segment(self):
        # "a%2Fb" is refused by nobody, but its "%" is encoded, so the server
        # decodes it back to the literal text "a%2Fb", never to "a/b".
        assert _seg("a%2Fb") == "a%252Fb"

    @pytest.mark.parametrize("raw,encoded", [
        ("a?b", "a%3Fb"),
        ("a#b", "a%23b"),
        ("a b", "a%20b"),
        ("did:agentx:bot-1", "did:agentx:bot-1"),
        (UUID_ID, UUID_ID),
    ])
    def test_encodes(self, raw, encoded):
        assert _seg(raw) == encoded

    def test_uuid_and_int_objects(self):
        assert _seg(UUID(UUID_ID)) == UUID_ID
        assert _seg(42) == "42"


# -- Every namespace refuses before sending ------------------------------------

class TestRefusedBeforeRequest:
    @pytest.mark.parametrize("name", sorted(CALLS))
    @pytest.mark.parametrize("bad", ["abc/replies", "../x", ".."])
    def test_no_request_sent(self, name, bad):
        with respx.mock(assert_all_called=False) as mock:
            anything = mock.route().mock(return_value=httpx.Response(200, json={}))
            with pytest.raises(ValueError):
                CALLS[name](make_client(), bad)
            assert not anything.called, f"{name} sent a request for {bad!r}"

    def test_async_client_refuses(self):
        client = AgentClient(base_url=BASE, agent_did=AGENT_DID)
        with respx.mock(assert_all_called=False) as mock:
            anything = mock.route().mock(return_value=httpx.Response(200, json={}))
            with pytest.raises(ValueError):
                asyncio.run(client.like("abc/../tasks/x/approve"))
            assert not anything.called


# -- Odd but harmless ids stay in their own segment ------------------------------

class TestEncodedOnTheWire:
    @pytest.mark.parametrize("raw,wire", [
        ("a?b", "/posts/a%3Fb"),
        ("a#b", "/posts/a%23b"),
        ("a%2Fb", "/posts/a%252Fb"),
    ])
    @respx.mock
    def test_posts_get(self, raw, wire):
        route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, json={}))
        make_client().posts.get(raw)
        assert route.calls.last.request.url.raw_path.decode() == wire

    @respx.mock
    def test_uuid_object_still_works(self):
        route = respx.get(f"{BASE}/posts/{UUID_ID}").mock(
            return_value=httpx.Response(200, json={"post_id": UUID_ID})
        )
        make_client().posts.get(UUID(UUID_ID))
        assert route.called

    @respx.mock
    def test_did_keeps_its_colons(self):
        route = respx.post(f"{BASE}/agents/did:agentx:other-1/follow").mock(
            return_value=httpx.Response(200, json={})
        )
        make_client().social.follow("did:agentx:other-1")
        assert route.called


# -- No raw interpolation left in the package ------------------------------------

def test_every_path_fstring_uses_seg():
    pkg = pathlib.Path(__file__).resolve().parents[1] / "agentx_sdk"
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for m in re.finditer(r'f"(/[^"]*)"', line):
                for expr in re.findall(r"\{([^{}]+)\}", m.group(1)):
                    if not expr.startswith("_seg("):
                        offenders.append(f"{path.name}:{n}: {{{expr}}}")
    assert offenders == [], "unwrapped path ids:\n" + "\n".join(offenders)
