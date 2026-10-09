"""
Guard: production runs the broker-free scheduler, not Celery.

Celery needed a Redis broker; its polling used up the Upstash free plan in
three days and took production down on 9 Oct 2026. Celery is removed from the
code (src/jobs/scheduler.py replaces it), so the old `celery ...` command in
`platform/fly.toml` would fail to start.

The engine may not edit the Fly config files (standing rule 6), so DrJ makes
the one-line edit (HUMAN_ACTIONS H34). Until then this check is xfail; once the
line is in it passes, and the marker can be removed so it becomes a hard guard
like test_fly_release_command.py.
"""
import tomllib
from pathlib import Path

import pytest

_PLATFORM = Path(__file__).resolve().parent.parent

# The exact line H34 tells DrJ to put under [processes].
H34_SCHEDULER = "python -m src.jobs.scheduler"


@pytest.mark.xfail(reason="waiting on DrJ: HUMAN_ACTIONS H34 (fly.toml scheduler line)",
                   strict=False)
def test_fly_scheduler_process_is_the_broker_free_scheduler():
    processes = tomllib.loads((_PLATFORM / "fly.toml").read_text())["processes"]
    assert processes["scheduler"] == H34_SCHEDULER


def test_h34_line_is_the_module_that_exists():
    assert (_PLATFORM / "src" / "jobs" / "scheduler.py").is_file()
    assert H34_SCHEDULER.split()[-1] == "src.jobs.scheduler"
