"""
Guard: CI must not run on the engine's draft PR (Sprint 13 T-1), but must still
run on every push to main (Deploy waits on that run) and once a PR is marked
ready for review.

There is deliberately no `workflow_dispatch`: Deploy fires on any successful CI
run whose branch is main, so a hand-started CI run on main would redeploy
production. To run CI on the draft PR, mark it "Ready for review".
"""
from pathlib import Path

import pytest
import yaml

_CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
_DRAFT_GUARD = "github.event_name != 'pull_request' || !github.event.pull_request.draft"


@pytest.fixture(scope="module")
def ci():
    return yaml.safe_load(_CI.read_text())


def _triggers(ci):
    # YAML 1.1 reads the bare key `on` as the boolean True.
    return ci.get("on", ci.get(True))


def test_push_to_main_still_runs_ci(ci):
    assert "main" in _triggers(ci)["push"]["branches"]


def test_pull_requests_run_when_marked_ready(ci):
    types = _triggers(ci)["pull_request"]["types"]
    assert {"opened", "reopened", "synchronize", "ready_for_review"} <= set(types)


def test_no_manual_trigger_that_could_redeploy_main(ci):
    assert "workflow_dispatch" not in _triggers(ci)


def test_every_job_skips_draft_pull_requests(ci):
    jobs = ci["jobs"]
    assert jobs
    for name, job in jobs.items():
        assert job.get("if") == _DRAFT_GUARD, f"job {name} runs on draft PRs"
