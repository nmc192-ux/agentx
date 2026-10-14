"""
Tests: deploy/vps/watchdog.sh (LR-3) — free alerts on the VPS.

Driven with fake `curl`, `psql` and `df` on PATH (PG_RUN=native), so no network, no database and
no real alert is ever sent. Pins what the sprint's acceptance criteria ask for:
  1. every check (api, ready, scheduler, backup, restore, disk) alerts exactly once on going bad,
     stays quiet while it stays bad, and sends exactly one "recovered" message;
  2. all ok on the first run sends nothing; a bad first run sends one alert;
  3. with neither ntfy nor Slack set it only logs, and the state still moves on;
  4. a failed delivery does not record the new state, so the next run tries again;
  5. no value from alerts.env (the ntfy topic, the Slack URL) ever appears in a message or the
     log, and alerts.env is read, never run;
  6. shellcheck is clean.
Plus one run of the scheduler query against a real local Postgres table (skipped without psql).
"""
import getpass
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy" / "vps" / "watchdog.sh"
NTFY = "https://ntfy.sh/agentx-SECRET-TOPIC-0123456789"
SLACK = "https://hooks.slack.com/services/T000/B000/SECRETSLACKTOKEN"

FAKE_CURL = r"""#!/usr/bin/env bash
# health checks: -w '%{http_code}' ... URL ; sends: --data-binary DATA ... URL
url="${@: -1}"
data=""; writeout=0
while (( $# )); do
  case "$1" in
    -w) writeout=1; shift ;;
    --data-binary) data="$2"; shift ;;
    -H) echo "header $2" >> "$FAKE/sent.log"; shift ;;
  esac
  shift
done
if (( writeout )); then
  case "$url" in
    */health/ready) printf '%s' "$(cat "$FAKE/ready")" ;;
    */health) printf '%s' "$(cat "$FAKE/health")" ;;
  esac
  exit 0
fi
printf 'send %s\ndata %s\n' "$url" "$data" >> "$FAKE/sent.log"
exit "$(cat "$FAKE/send_exit" 2>/dev/null || echo 0)"
"""

FAKE_PSQL = r"""#!/usr/bin/env bash
v="$(cat "$FAKE/sched_age")"
[[ "$v" == fail ]] && { echo "psql: connection refused" >&2; exit 2; }
echo "$v"
"""

FAKE_DF = r"""#!/usr/bin/env bash
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/sda1 1000 500 500 $(cat "$FAKE/disk")% /"
"""


class Box:
    """One VPS as the watchdog sees it, all of it fake."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.fake = tmp / "fake"
        self.bin = tmp / "bin"
        self.backups = tmp / "backups"
        for d in (self.fake, self.bin, self.backups):
            d.mkdir()
        for name, body in (("curl", FAKE_CURL), ("psql", FAKE_PSQL), ("df", FAKE_DF)):
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)
        self.alerts = tmp / "alerts.env"
        self.alerts.write_text(f"NTFY_URL={NTFY}\nSLACK_WEBHOOK_URL='{SLACK}'\n")
        self.set(health="200", ready="200", sched_age="120", disk="40")
        self.fresh_backup()
        (self.backups / "restore-test.status").write_text("ok 2026-10-15T03:47:00Z agentx-x.dump 40 tables 900 rows\n")

    def set(self, **values: str) -> None:
        for k, v in values.items():
            (self.fake / k).write_text(v)

    def fresh_backup(self, age_h: float = 1) -> Path:
        f = self.backups / f"agentx-{int(time.time() * 1000)}.dump"
        f.write_bytes(b"PGDMP" + b"x" * 100)
        t = time.time() - age_h * 3600
        os.utime(f, (t, t))
        return f

    def run(self, **env: str) -> subprocess.CompletedProcess:
        (self.fake / "sent.log").unlink(missing_ok=True)
        e = {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.tmp), "FAKE": str(self.fake),
            "AGENTX_DIR": str(self.tmp), "PG_RUN": "native", "BACKUP_DIR": str(self.backups),
            "ALERTS_ENV": str(self.alerts), "API_URL": "https://api.example.test", "HOST_LABEL": "vps",
            **env,
        }
        return subprocess.run(["bash", str(SCRIPT)], env=e, capture_output=True, text=True, timeout=60)

    def sent(self) -> list[str]:
        log = self.fake / "sent.log"
        return log.read_text().splitlines() if log.exists() else []

    def titles(self) -> list[str]:
        """One entry per ntfy message (the Title header)."""
        return [l.removeprefix("header Title: ") for l in self.sent() if l.startswith("header Title: ")]


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def test_all_ok_first_run_sends_nothing(box):
    r = box.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.sent() == []
    for name in ("api", "ready", "scheduler", "backup", "restore", "disk"):
        assert f"{name} ok" in r.stdout
    assert (box.backups / "watchdog.state").read_text().split() == [
        "api", "ok", "ready", "ok", "scheduler", "ok", "backup", "ok", "restore", "ok", "disk", "ok"]


def _old_status(box):
    f = box.backups / "restore-test.status"
    t = time.time() - 30 * 3600
    os.utime(f, (t, t))


def _no_backup(box):
    for f in box.backups.glob("agentx-*.dump"):
        f.unlink()


BREAKERS = {
    "api": (lambda b: b.set(health="502"), lambda b: b.set(health="200"), "answered 502"),
    "api-unreachable": (lambda b: b.set(health="000"), lambda b: b.set(health="200"), "answered 000"),
    "ready": (lambda b: b.set(ready="503"), lambda b: b.set(ready="200"), "answered 503"),
    "scheduler": (lambda b: b.set(sched_age=str(45 * 60)), lambda b: b.set(sched_age="60"), "for 45 min"),
    "scheduler-db-down": (lambda b: b.set(sched_age="fail"), lambda b: b.set(sched_age="60"), "could not read"),
    "scheduler-never": (lambda b: b.set(sched_age="-1"), lambda b: b.set(sched_age="60"), "never finished"),
    "backup": (lambda b: [f.unlink() for f in b.backups.glob("agentx-*.dump")] and b.fresh_backup(30),
               lambda b: b.fresh_backup(), "no backup newer than 26 h"),
    "backup-missing": (_no_backup, lambda b: b.fresh_backup(), "no agentx-*.dump"),
    "restore": (lambda b: (b.backups / "restore-test.status").write_text("fail 2026-10-15T03:47:00Z backup is truncated\n"),
                lambda b: (b.backups / "restore-test.status").write_text("ok 2026-10-16T03:47:00Z fine\n"),
                "restore test failed: 2026-10-15T03:47:00Z backup is truncated"),
    "restore-stale": (_old_status, lambda b: (b.backups / "restore-test.status").write_text("ok now\n"),
                      "has not run for over 26 h"),
    "disk": (lambda b: b.set(disk="91"), lambda b: b.set(disk="60"), "91% used"),
}


@pytest.mark.parametrize("case", sorted(BREAKERS))
def test_each_condition_alerts_once_then_recovers_once(box, case):
    check = case.split("-")[0]
    breaks, heals, words = BREAKERS[case]
    assert box.run().returncode == 0

    breaks(box)
    r = box.run()
    assert r.returncode == 1
    assert box.titles() == [f"AgentX ALERT (vps): {check}"]
    assert any(words in l for l in box.sent() if l.startswith("data ")), box.sent()
    # Slack got the same alert once.
    assert sum(1 for l in box.sent() if l == f"send {SLACK}") == 1

    for _ in range(3):  # still bad: no flood
        r = box.run()
        assert r.returncode == 1
        assert box.sent() == []

    heals(box)
    r = box.run()
    assert r.returncode == 0, r.stdout
    assert box.titles() == [f"AgentX OK (vps): {check} recovered"]
    assert box.run().returncode == 0
    assert box.sent() == []


def test_bad_on_first_run_alerts_once(box):
    box.set(health="502", disk="99")
    box.run()
    assert sorted(box.titles()) == ["AgentX ALERT (vps): api", "AgentX ALERT (vps): disk"]
    box.run()
    assert box.sent() == []


def test_log_only_without_ntfy_or_slack(box):
    box.alerts.write_text("# nothing set\nNTFY_URL=\n")
    box.set(ready="503")
    r = box.run()
    assert r.returncode == 1
    assert box.sent() == []
    assert "log only" in r.stdout
    assert "ready bad" in r.stdout
    # The state moved on: a second run does not repeat the log-only notice.
    assert "log only" not in box.run().stdout


def test_missing_alerts_file_is_log_only(box):
    box.alerts.unlink()
    box.set(health="500")
    r = box.run()
    assert r.returncode == 1 and box.sent() == [] and "log only" in r.stdout


def test_failed_delivery_is_retried_next_run(box):
    box.set(health="502", send_exit="7")
    box.run()
    assert len(box.titles()) == 1
    assert "could not reach ntfy" in box.run().stdout  # tried again, still failing
    box.set(send_exit="0")
    box.run()
    assert box.titles() == ["AgentX ALERT (vps): api"]
    box.run()
    assert box.sent() == []


def test_ntfy_only_or_slack_only(box):
    box.alerts.write_text(f"SLACK_WEBHOOK_URL={SLACK}\n")
    box.set(disk="95")
    box.run()
    assert [l for l in box.sent() if l.startswith("send ")] == [f"send {SLACK}"]
    data = [l for l in box.sent() if l.startswith("data ")][0]
    assert data.startswith('data {"text":"AgentX ALERT (vps): disk: disk 95% used')


def test_no_secret_in_messages_or_log(box):
    box.alerts.write_text(f"NTFY_URL={NTFY}\nSLACK_WEBHOOK_URL={SLACK}\n")
    for k in ("health", "ready"):
        box.set(**{k: "502"})
    box.set(sched_age="fail", disk="99")
    _no_backup(box)
    r1 = box.run()
    for k in ("health", "ready"):
        box.set(**{k: "200"})
    box.set(sched_age="5", disk="10")
    box.fresh_backup()
    r2 = box.run()
    messages = [l for l in box.sent() if l.startswith(("data ", "header "))]
    assert messages
    for text in [*messages, r1.stdout, r1.stderr, r2.stdout, r2.stderr]:
        assert "SECRET" not in text


def test_alerts_env_is_never_executed(box):
    marker = box.tmp / "pwned"
    box.alerts.write_text(f"touch {marker}\nNTFY_URL=$(touch {marker})\n")
    box.set(health="500")
    box.run()
    assert not marker.exists()


def test_restore_status_text_is_cleaned(box):
    (box.backups / "restore-test.status").write_bytes(b"fail \x1b[31mred\x07 " + b"y" * 500 + b"\nsecond line\n")
    box.run()
    data = [l for l in box.sent() if l.startswith("data ")][0]
    assert "\x1b" not in data and "\x07" not in data and "second line" not in data
    assert len(data) < 260


def test_shellcheck_clean():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck not installed")
    r = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_alerts_example_has_no_values():
    example = REPO / "deploy" / "vps" / "alerts.env.example"
    for line in example.read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert name in ("NTFY_URL", "SLACK_WEBHOOK_URL") and value == "", line


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("psql") is None, reason="Postgres client tools not installed")
def test_scheduler_query_against_real_postgres(box):
    """The SQL the watchdog runs works on the real table shape from migration 049."""
    user, db = getpass.getuser(), "agentx_smoke_watchdog"

    def pg(sql, d="postgres"):
        subprocess.run(["psql", "-X", "-At", "-h", "localhost", "-U", user, "-d", d, "-v", "ON_ERROR_STOP=1",
                        "-c", sql], check=True, capture_output=True)

    try:
        pg(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
    except subprocess.CalledProcessError:
        pytest.skip("local Postgres not reachable")
    pg(f"CREATE DATABASE {db}")
    try:
        pg("""CREATE TABLE scheduler_job_runs (job_name TEXT PRIMARY KEY, last_started_at TIMESTAMPTZ NOT NULL,
              last_finished_at TIMESTAMPTZ, last_status TEXT NOT NULL DEFAULT 'running',
              last_summary JSONB NOT NULL DEFAULT '{}'::jsonb)""", db)
        (box.bin / "psql").unlink()  # the real psql from here on
        env = {"PGHOST": "localhost", "PGUSER": user, "PGDATABASE": db, "CHECKS": "scheduler"}
        r = box.run(**env)
        assert r.returncode == 1 and "never finished" in r.stdout
        pg("""INSERT INTO scheduler_job_runs VALUES
              ('founder_tick', now() - interval '3 min', now() - interval '2 min', 'ok', '{}'),
              ('release', now(), now(), 'failed', '{}')""", db)
        r = box.run(**env)
        assert r.returncode == 0 and "last scheduler job ok 2 min ago" in r.stdout, r.stdout
        pg("UPDATE scheduler_job_runs SET last_finished_at = now() - interval '40 min' WHERE last_status = 'ok'", db)
        r = box.run(**env)
        assert r.returncode == 1 and "for 40 min" in r.stdout
    finally:
        pg(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
