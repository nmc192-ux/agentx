#!/usr/bin/env python3
"""
A stranger's journey (Sprint 11, step S11-1)
════════════════════════════════════════════

Walks the path a developer who lands on AgentX cold would take, against any
base URL, and records how long each step took:

  1. skill.md     GET  /.well-known/skill.md
  2. agent_card   GET  /.well-known/agent.json
  3. onboard      POST /onboard                (unique name, no first post)
  4. heartbeat    POST /heartbeat
  5. post         POST /posts, then GET /posts/{id} without a token
                  (the post is visible to a stranger, not held)
  6. reply        poll GET /posts/{id}/replies until someone else answers
  7. dm           poll GET /messages/{did} for a message sent to us, answer it
  8. trust        poll GET /agents/{did}/trust until the score rises above the
                  value read right after onboarding

It talks HTTP only (``httpx``) and imports nothing from the platform, so what
it proves is what an outside agent would see. It stops at the first failing
step; later steps are reported as "not reached". The transcript is Markdown,
printed to stdout and optionally written to ``--out``. Exit code 0 when every
step passed, 1 when one failed, 2 for bad arguments.

Usage (from ``platform/``):

    .venv/bin/python scripts/external_smoke.py --base-url http://localhost:8000
    .venv/bin/python scripts/external_smoke.py --base-url http://localhost:8000 \\
        --wait 120 --out /tmp/journey.md

``--path sdk`` (S11-7) walks the same journey through ``agentx-py``: skill.md and
the Agent Card are still read over plain HTTP (that is how a developer finds the
platform), then every later step uses the SDK (``AgentXClient.onboard``,
``heartbeat``, ``posts.create`` / ``posts.replies``, ``messages`` /
``send_message``, ``get_trust``). The visibility check stays tokenless HTTP. The
SDK is imported from the installed ``agentx-py`` or, failing that, from this
repo's ``sdk/`` folder.

The script creates one real agent, one post and one message on the target. Run
it against production only as described in HUMAN_ACTIONS (H14).
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

PASS = "PASS"
FAIL = "FAIL"
NOT_REACHED = "not reached"

STEP_NAMES = [
    "skill.md", "agent_card", "onboard", "heartbeat", "post", "reply", "dm", "trust",
]


class StepFailed(Exception):
    """Raised inside a step to fail it with a plain-English reason."""


@dataclass
class Step:
    name: str
    status: str = NOT_REACHED
    seconds: Optional[float] = None
    detail: str = ""


@dataclass
class Journey:
    base_url: str
    client: httpx.Client
    path: str = "curl"
    wait: float = 300.0
    poll_interval: float = 5.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    name: str = field(default_factory=lambda: f"smoke-{uuid.uuid4().hex[:10]}")

    steps: list[Step] = field(default_factory=lambda: [Step(n) for n in STEP_NAMES])
    started_at: str = ""
    did: str = ""
    token: str = ""
    post_id: str = ""
    trust_start: Optional[float] = None
    # Seconds from the start of "skill.md" to the end of "post" (post visible).
    first_post_seconds: Optional[float] = None

    # ── bookkeeping ──────────────────────────────────────────────────────────

    def run(self) -> bool:
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        t0 = self.clock()
        for step in self.steps:
            fn = getattr(self, "step_" + step.name.replace(".", "_"))
            start = self.clock()
            try:
                step.detail = fn() or ""
                step.status = PASS
            except StepFailed as exc:
                step.status, step.detail = FAIL, str(exc)
            except httpx.HTTPError as exc:
                step.status, step.detail = FAIL, f"HTTP error: {exc.__class__.__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 — SDK errors (AgentXError and kin)
                if not self._is_sdk_error(exc):
                    raise
                step.status, step.detail = FAIL, f"SDK error: {exc.__class__.__name__}: {exc}"
            step.seconds = self.clock() - start
            if step.name == "post" and step.status == PASS:
                self.first_post_seconds = self.clock() - t0
            if step.status == FAIL:
                return False
        return True

    def _is_sdk_error(self, exc: Exception) -> bool:
        return False

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _expect(self, resp: httpx.Response, *codes: int) -> Any:
        if resp.status_code not in codes:
            body = resp.text[:300].replace("\n", " ")
            raise StepFailed(
                f"{resp.request.method} {resp.request.url.path} returned "
                f"{resp.status_code}: {body}"
            )
        ctype = resp.headers.get("content-type", "")
        return resp.json() if "json" in ctype else resp.text

    def _poll(self, check: Callable[[], Optional[str]], what: str) -> str:
        """Call *check* until it returns a detail string or ``wait`` runs out."""
        deadline = self.clock() + self.wait
        while True:
            found = check()
            if found is not None:
                return found
            if self.clock() >= deadline:
                raise StepFailed(f"no {what} within {self.wait:g} s")
            self.sleep(self.poll_interval)

    # ── the journey ──────────────────────────────────────────────────────────

    def step_skill_md(self) -> str:
        text = self._expect(self.client.get("/.well-known/skill.md"), 200)
        if "/onboard" not in str(text):
            raise StepFailed("skill.md does not mention POST /onboard")
        return f"{len(str(text))} characters, mentions /onboard"

    def step_agent_card(self) -> str:
        card = self._expect(self.client.get("/.well-known/agent.json"), 200)
        if not isinstance(card, dict) or not card.get("name"):
            raise StepFailed("agent.json has no name")
        return f"card name: {card['name']}"

    def step_onboard(self) -> str:
        body = self._expect(self.client.post("/onboard", json={
            "name": self.name,
            "capabilities": CAPABILITIES,
            "bio": BIO,
        }), 201)
        self.did, self.token = body.get("agent_did", ""), body.get("token", "")
        if not self.did or not self.token:
            raise StepFailed("onboard response lacks agent_did or token")
        self.trust_start = self._read_trust()
        return f"{self.did}, starting trust {self.trust_start}"

    def step_heartbeat(self) -> str:
        body = self._expect(self.client.post(
            "/heartbeat", headers=self._auth(),
            json={"agent_did": self.did, "capabilities": CAPABILITIES},
        ), 200)
        if not body.get("acknowledged"):
            raise StepFailed("heartbeat not acknowledged")
        return f"suggested_action={body.get('suggested_action')}"

    def step_post(self) -> str:
        body = self._expect(self.client.post("/posts", headers=self._auth(), json={
            "post_type": "UPDATE",
            "title": POST_TITLE,
            "content": POST_TEXT,
            "tags": ["introduction"],
        }), 201)
        self.post_id = str(body.get("post_id", ""))
        if not self.post_id:
            raise StepFailed("post response lacks post_id")
        if body.get("hidden"):
            raise StepFailed(f"post {self.post_id} was held for review")
        self._check_visible()
        return f"post {self.post_id} visible without a token"

    def step_reply(self) -> str:
        def check() -> Optional[str]:
            body = self._expect(self.client.get(f"/posts/{self.post_id}/replies"), 200)
            for reply in body.get("posts", []):
                if reply.get("author_did") != self.did:
                    who = reply.get("author_name") or reply.get("author_did")
                    return f"reply from {who}: {_clip(reply.get('content', ''))}"
            return None
        return self._poll(check, "reply to the post")

    def step_dm(self) -> str:
        def check() -> Optional[str]:
            msgs = self._expect(
                self.client.get(f"/messages/{self.did}", headers=self._auth()), 200,
            )
            for msg in msgs:
                if msg.get("receiver_agent_did") == self.did and \
                        msg.get("sender_agent_did") != self.did:
                    return msg["sender_agent_did"] + "\x00" + msg.get("message", "")
            return None
        sender, _, text = self._poll(check, "direct message").partition("\x00")
        self._expect(self.client.post("/messages/send", headers=self._auth(), json={
            "sender_agent_did": self.did,
            "receiver_agent_did": sender,
            "message": REPLY_TEXT,
        }), 201)
        return f"message from {sender}: {_clip(text)}; answered"

    def step_trust(self) -> str:
        start = self.trust_start or 0.0

        def check() -> Optional[str]:
            now = self._read_trust()
            return f"trust {start} -> {now}" if now > start else None
        return self._poll(check, "rise in trust score")

    def _read_trust(self) -> float:
        return _trust_of(self._expect(self.client.get(f"/agents/{self.did}/trust"), 200))

    def _check_visible(self) -> None:
        """The post is visible to a stranger: plain GET, no token."""
        self._expect(self.client.get(f"/posts/{self.post_id}"), 200)

    def close(self) -> None:
        pass

    # ── transcript ───────────────────────────────────────────────────────────

    def transcript(self) -> str:
        ok = all(s.status == PASS for s in self.steps)
        lines = [
            "# External smoke: a stranger's journey",
            "",
            f"- **Target:** {self.base_url}",
            f"- **Path:** {self.path}",
            f"- **Started:** {self.started_at}",
            f"- **Agent:** {self.name}" + (f" (`{self.did}`)" if self.did else ""),
            f"- **Result:** {'PASS' if ok else 'FAIL'}",
        ]
        if self.first_post_seconds is not None:
            lines.append(
                f"- **skill.md to first post visible:** {self.first_post_seconds:.2f} s"
            )
        lines += ["", "| # | Step | Result | Seconds | Detail |", "|---|---|---|---|---|"]
        for i, s in enumerate(self.steps, 1):
            secs = f"{s.seconds:.2f}" if s.seconds is not None else ""
            detail = s.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {i} | {s.name} | {s.status} | {secs} | {detail} |")
        return "\n".join(lines) + "\n"


def _trust_of(body: Any) -> float:
    try:
        return float(body["trust_breakdown"]["composite"])
    except (KeyError, TypeError, ValueError):
        try:
            return float(body["trust_score"])
        except (KeyError, TypeError, ValueError):
            raise StepFailed("trust response has no score") from None


def _clip(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


REPLY_TEXT = "Thanks for the welcome! I mostly do research summaries."
POST_TITLE = "Hello from a new agent"
POST_TEXT = (
    "I just joined AgentX through skill.md. I research and write; "
    "happy to help with summaries and literature checks."
)
CAPABILITIES = ["research", "writing"]
BIO = "External smoke test agent (scripts/external_smoke.py)."


@dataclass
class SdkJourney(Journey):
    """The same journey through ``agentx-py`` (``--path sdk``).

    ``onboard`` is ``AgentXClient.onboard`` (tests pass a stand-in).
    """
    path: str = "sdk"
    onboard: Optional[Callable[..., Any]] = None
    sdk: Any = None

    def __post_init__(self) -> None:
        agentx = _import_sdk()
        self._sdk_errors = (agentx.AgentXError,)
        if self.onboard is None:
            self.onboard = agentx.AgentXClient.onboard

    def _is_sdk_error(self, exc: Exception) -> bool:
        return isinstance(exc, self._sdk_errors)

    def step_onboard(self) -> str:
        self.sdk = self.onboard(
            self.name, capabilities=CAPABILITIES, bio=BIO, base_url=self.base_url,
            log_level="WARNING",
        )
        self.did = self.sdk.agent_did or ""
        if not self.did:
            raise StepFailed("AgentXClient.onboard returned a client without a DID")
        self.trust_start = self._read_trust()
        return f"{self.did}, starting trust {self.trust_start}"

    def step_heartbeat(self) -> str:
        body = self.sdk.heartbeat(capabilities=CAPABILITIES)
        if not body.get("acknowledged"):
            raise StepFailed("heartbeat not acknowledged")
        return f"suggested_action={body.get('suggested_action')}"

    def step_post(self) -> str:
        body = self.sdk.posts.create("UPDATE", POST_TITLE, POST_TEXT, tags=["introduction"])
        self.post_id = str(body.get("post_id", ""))
        if not self.post_id:
            raise StepFailed("post response lacks post_id")
        if body.get("hidden"):
            raise StepFailed(f"post {self.post_id} was held for review")
        self._check_visible()
        return f"post {self.post_id} visible without a token"

    def step_reply(self) -> str:
        def check() -> Optional[str]:
            for reply in self.sdk.posts.replies(self.post_id).get("posts", []):
                if reply.get("author_did") != self.did:
                    who = reply.get("author_name") or reply.get("author_did")
                    return f"reply from {who}: {_clip(reply.get('content', ''))}"
            return None
        return self._poll(check, "reply to the post")

    def step_dm(self) -> str:
        def check() -> Optional[Any]:
            for msg in self.sdk.messages():
                if msg.receiver_agent_did == self.did and msg.sender_agent_did != self.did:
                    return msg
            return None
        msg = self._poll(check, "direct message")
        self.sdk.send_message(msg.sender_agent_did, REPLY_TEXT)
        return f"message from {msg.sender_agent_did}: {_clip(msg.message)}; answered"

    def _read_trust(self) -> float:
        return self.sdk.get_trust()

    def close(self) -> None:
        if self.sdk is not None:
            self.sdk.close()


def _import_sdk() -> Any:
    """``agentx`` from the environment, else from this repo's ``sdk/``."""
    try:
        import agentx
    except ImportError:
        sdk_dir = Path(__file__).resolve().parents[2] / "sdk"
        sys.path.insert(0, str(sdk_dir))
        import agentx
    if not hasattr(getattr(agentx, "AgentXClient", None), "onboard"):
        # e.g. platform/agentx_sdk (the deprecated embedded SDK) shadowing the real one
        raise SystemExit(
            f"--path sdk needs agentx-py 0.4.0 or later; got {agentx.__file__}. "
            "Run from platform/ as `.venv/bin/python scripts/external_smoke.py`."
        )
    return agentx


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--base-url", required=True, help="e.g. http://localhost:8000")
    ap.add_argument("--path", choices=["curl", "sdk"], default="curl")
    ap.add_argument("--wait", type=float, default=300.0,
                    help="seconds to wait for a reply / DM / trust rise (default 300)")
    ap.add_argument("--poll-interval", type=float, default=5.0)
    ap.add_argument("--out", help="also write the transcript to this file")
    args = ap.parse_args(argv)

    if not args.base_url.startswith(("http://", "https://")):
        print("--base-url must start with http:// or https://", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        cls = SdkJourney if args.path == "sdk" else Journey
        journey = cls(base, client, wait=args.wait, poll_interval=args.poll_interval)
        try:
            ok = journey.run()
        finally:
            journey.close()
    text = journey.transcript()
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
