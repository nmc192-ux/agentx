"""Unit tests for scripts/external_smoke.py (S11-1).

The journey runs against a fake platform (httpx.MockTransport); these tests pin
the step bookkeeping, the stop-at-first-failure rule, polling and the transcript.
"""
import importlib.util
import sys
from pathlib import Path

import httpx

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "external_smoke.py"
_spec = importlib.util.spec_from_file_location("external_smoke", _PATH)
smoke = importlib.util.module_from_spec(_spec)
sys.modules["external_smoke"] = smoke  # dataclasses look the module up
_spec.loader.exec_module(smoke)

DID = "did:agentx:smoke-abc"
FOUNDER = "did:agentx:founder-sage"
POST_ID = "11111111-1111-1111-1111-111111111111"


class FakePlatform:
    """A tiny stand-in for the API. Flags switch individual behaviours off."""

    def __init__(self, reply=True, dm=True, trust_rises=True, hidden=False):
        self.reply, self.dm, self.trust_rises, self.hidden = reply, dm, trust_rises, hidden
        self.trust = 0.1
        self.answered = False
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        self.calls.append(f"{method} {path}")
        if path == "/.well-known/skill.md":
            return httpx.Response(200, text="# AgentX\ncurl -X POST /onboard")
        if path == "/.well-known/agent.json":
            return httpx.Response(200, json={"name": "AgentX"})
        if path == "/onboard":
            return httpx.Response(201, json={"agent_did": DID, "token": "tok"})
        if path == f"/agents/{DID}/trust":
            return httpx.Response(200, json={"trust_breakdown": {"composite": self.trust}})
        if path == "/heartbeat":
            assert req.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, json={"acknowledged": True,
                                             "suggested_action": "browse_feed"})
        if path == "/posts" and method == "POST":
            return httpx.Response(201, json={"post_id": POST_ID, "hidden": self.hidden})
        if path == f"/posts/{POST_ID}":
            assert "authorization" not in req.headers
            return httpx.Response(200, json={"post_id": POST_ID})
        if path == f"/posts/{POST_ID}/replies":
            posts = [{"author_did": FOUNDER, "author_name": "Sage",
                      "content": "Welcome!"}] if self.reply else []
            return httpx.Response(200, json={"posts": posts})
        if path == f"/messages/{DID}":
            msgs = [{"sender_agent_did": FOUNDER, "receiver_agent_did": DID,
                     "message": "What do you research?"}] if self.dm else []
            return httpx.Response(200, json=msgs)
        if path == "/messages/send":
            self.answered = True
            if self.trust_rises:
                self.trust = 0.11
            return httpx.Response(201, json={"message_id": "m1"})
        return httpx.Response(404, json={"detail": "nope"})


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def _journey(platform, wait=10.0):
    clock = FakeClock()
    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(platform))
    return smoke.Journey("http://test", client, wait=wait, poll_interval=2.0,
                         clock=clock, sleep=clock.sleep, name="smoke-test")


def test_full_journey_passes():
    platform = FakePlatform()
    j = _journey(platform)
    assert j.run() is True
    assert [s.status for s in j.steps] == [smoke.PASS] * len(smoke.STEP_NAMES)
    assert platform.answered
    assert "0.1 -> 0.11" in j.steps[-1].detail
    assert j.first_post_seconds is not None
    text = j.transcript()
    assert "**Result:** PASS" in text and "skill.md to first post visible" in text


def test_stops_at_first_failure_and_marks_rest_not_reached():
    platform = FakePlatform(reply=False)
    j = _journey(platform, wait=6.0)
    assert j.run() is False
    by_name = {s.name: s for s in j.steps}
    assert by_name["post"].status == smoke.PASS
    assert by_name["reply"].status == smoke.FAIL
    assert "no reply to the post within 6 s" in by_name["reply"].detail
    assert by_name["dm"].status == by_name["trust"].status == smoke.NOT_REACHED
    assert by_name["dm"].seconds is None
    # Polled until the deadline: t=0,2,4,6 → four reads of the replies.
    assert platform.calls.count(f"GET /posts/{POST_ID}/replies") == 4
    assert not any(c.startswith("GET /messages") for c in platform.calls)
    text = j.transcript()
    assert "**Result:** FAIL" in text
    assert "| 7 | dm | not reached |  |  |" in text


def test_held_post_fails_the_post_step():
    j = _journey(FakePlatform(hidden=True))
    assert j.run() is False
    assert j.steps[4].status == smoke.FAIL and "held for review" in j.steps[4].detail
    assert j.first_post_seconds is None


def test_trust_that_never_rises_fails():
    j = _journey(FakePlatform(trust_rises=False), wait=4.0)
    assert j.run() is False
    assert j.steps[-1].status == smoke.FAIL
    assert "rise in trust score" in j.steps[-1].detail


def test_http_status_error_is_reported_with_body():
    def broken(req):
        return httpx.Response(503, text="down for maintenance")
    j = _journey(broken)
    assert j.run() is False
    assert j.steps[0].status == smoke.FAIL
    assert "503" in j.steps[0].detail and "down for maintenance" in j.steps[0].detail


def test_connection_error_fails_cleanly():
    def refuse(req):
        raise httpx.ConnectError("refused", request=req)
    j = _journey(refuse)
    assert j.run() is False
    assert "ConnectError" in j.steps[0].detail


def test_pipes_in_detail_do_not_break_the_table():
    j = _journey(FakePlatform())
    j.steps[0].status, j.steps[0].detail, j.steps[0].seconds = smoke.PASS, "a|b", 0.5
    assert "a\\|b" in j.transcript()


def test_bad_arguments_exit_2():
    assert smoke.main(["--base-url", "localhost:8000"]) == 2
    assert smoke.main(["--base-url", "http://x", "--path", "sdk"]) == 2
