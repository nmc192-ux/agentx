"""Unit tests for the pure parts of scripts/smoke_routers.py (S9-4).

The harness itself needs local Postgres + Redis and is run by hand; these
tests pin its safety guard and its request-building logic.
"""
import argparse
import importlib.util
from pathlib import Path

from src.router_config import DEFAULT_DISABLED_ROUTERS

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke_routers.py"
_spec = importlib.util.spec_from_file_location("smoke_routers", _PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

CTX = {"did": "did:agentx:smoke-1", "token": "t", "post_id": "11111111-1111-1111-1111-111111111111"}


def _args(disabled=None, enable=None):
    return argparse.Namespace(disabled=disabled, enable=enable)


def test_refuses_non_scratch_database():
    assert smoke.main(["--db", "agentx", "--no-migrate"]) == 2


def test_default_list_is_repo_default():
    assert smoke.effective_disabled(_args()) == list(DEFAULT_DISABLED_ROUTERS)


def test_enable_removes_from_default():
    out = smoke.effective_disabled(_args(enable="memory, Graph"))
    assert "memory" not in out and "graph" not in out
    assert "nodes" in out


def test_explicit_empty_list_enables_everything():
    assert smoke.effective_disabled(_args(disabled="")) == []


def test_build_requests_fills_params():
    spec = {
        "paths": {
            "/agents/{agent_did}": {"get": {"parameters": [
                {"name": "agent_did", "in": "path", "schema": {"type": "string"}}]}},
            "/posts/{post_id}": {"get": {"parameters": [
                {"name": "post_id", "in": "path", "schema": {"type": "string", "format": "uuid"}}]}},
            "/tasks/{task_id}": {"get": {"parameters": [
                {"name": "task_id", "in": "path", "schema": {"type": "string"}}]}},
            "/search": {"get": {"parameters": [
                {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                {"name": "limit", "in": "query", "schema": {"type": "integer"}}]}},
            "/pages/{n}": {"get": {"parameters": [
                {"name": "n", "in": "path", "schema": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}]}},
            "/posts": {"post": {}},
        }
    }
    reqs = {t: (p, q) for t, p, q in smoke.build_requests(spec, CTX)}
    assert "/posts" not in reqs  # GET only
    assert reqs["/agents/{agent_did}"][0] == "/agents/did:agentx:smoke-1"
    assert reqs["/posts/{post_id}"][0] == f"/posts/{CTX['post_id']}"
    assert reqs["/tasks/{task_id}"][0] == f"/tasks/{smoke.ZERO_UUID}"
    assert reqs["/search"][1] == {"q": "smoke"}  # optional params left out
    assert reqs["/pages/{n}"][0] == "/pages/1"
