"""
Guard: the 1 Nov launch-day runbook (PLAN LR-4) stays followable.

DrJ runs it top to bottom without the engine, so a renamed script or a step
with no way back would surface on the day. Checks: every repo path and
`bash <script>.sh` it names exists, every step has a time and a non-empty
undo line, launch-day times never go backwards, the steps the sprint spec
requires are present, and nothing in it looks like a secret.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO / "platform" / "docs" / "execution" / "launch_day_runbook.md"

_STEP = re.compile(r"^### ([PL])(\d{2}) · ([^·]+) · ([^—]+) — (.+)$", re.M)
_REPO_PATH = re.compile(
    r"(?<![\w/.-])((?:deploy|platform|sdk|skills|ui|\.github)/[\w./-]*\w)")


def _text() -> str:
    return _RUNBOOK.read_text()


def _steps() -> list[tuple[str, int, str, str]]:
    """(kind, number, time, body) for every ### P/L step."""
    text = _text()
    heads = list(_STEP.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].split("\n---\n")[0].split("\n## ")[0]
        out.append((m.group(1), int(m.group(2)), m.group(3).strip(), body))
    return out


def test_runbook_exists_and_has_both_parts():
    steps = _steps()
    kinds = {k for k, *_ in steps}
    assert kinds == {"P", "L"}
    assert len([s for s in steps if s[0] == "L"]) >= 30


@pytest.mark.parametrize("kind", ["P", "L"])
def test_steps_are_numbered_in_order_without_gaps(kind):
    numbers = [n for k, n, *_ in _steps() if k == kind]
    assert numbers == list(range(1, len(numbers) + 1))


def test_every_step_has_must_see_and_a_non_empty_undo():
    for kind, n, _, body in _steps():
        name = f"{kind}{n:02d}"
        assert "**Run" in body, name
        assert "**You must see:**" in body, name
        assert "**If not:**" in body, name
        undo = re.search(r"\*\*Undo:\*\*\s*(.+)", body)
        assert undo and len(undo.group(1).strip()) > 5, f"{name} has no undo line"


def test_launch_day_times_never_go_backwards():
    times = [t for k, _, t, _ in _steps() if k == "L"]
    for t in times:
        assert re.fullmatch(r"\d{2}:\d{2}", t), t
    assert times == sorted(times)


def test_every_repo_path_named_exists():
    named = set(_REPO_PATH.findall(_text()))
    assert named, "expected the runbook to name repo files"
    missing = sorted(p for p in named if not (_REPO / p).exists())
    assert not missing, missing


def test_every_script_run_with_bash_exists_in_deploy_vps():
    scripts = set(re.findall(r"\bbash ([\w-]+\.sh)\b", _text()))
    assert {"db_move.sh", "smoke.sh", "watchdog.sh"} <= scripts
    for name in scripts:
        assert (_REPO / "deploy" / "vps" / name).is_file(), name


def test_db_move_subcommands_named_exist():
    script = (_REPO / "deploy" / "vps" / "db_move.sh").read_text()
    for sub in set(re.findall(r"bash db_move\.sh ([a-z-]+)", _text())):
        assert re.search(rf"^\s*{re.escape(sub)}\)", script, re.M), sub


def test_files_the_deploy_does_not_copy_are_copied_by_hand():
    """deploy-vps.yml copies four files; the runbook must scp the others it runs."""
    workflow = (_REPO / ".github" / "workflows" / "deploy-vps.yml").read_text()
    text = _text()
    for name in ("watchdog.sh", "alerts.env.example", "smoke.sh"):
        assert f"deploy/vps/{name}" not in workflow
        assert f"deploy/vps/{name}" in text, name


def test_required_steps_are_present():
    text = _text()
    for needle in (
        "Disable workflow",                       # Fly Deploy off for good
        "bash db_move.sh verify",                 # H36 B7
        "AGENTX_DB_ENV=/etc/agentx/db.env",       # H36 B8
        "Deploy to VPS",                          # first deploy
        "A 2.25.235.174",                         # DNS api -> VPS
        "--profile scheduler up -d scheduler",    # scheduler on
        "bash db_move.sh restore-test",           # tested restore
        "bash watchdog.sh",                       # alerts on
        "Fly-Client-IP: 203.0.113.9",             # spoofed-address check
        "sdk-v0.4.0",                             # H12
        "@agentx/sdk",                            # H26
        "agentx-mcp",                             # H31
        "clawhub",                                # H32
        "H28",                                    # announcement
        "CORS_ORIGINS",                           # the website may call the VPS
        "fly scale count app=0",                  # Fly to zero
    ):
        assert needle in text, needle


def test_announcement_is_the_last_action_before_reporting():
    steps = [(n, body) for k, n, _, body in _steps() if k == "L"]
    announce = [n for n, body in steps if "H28" in body and "alpha_announcement" in body]
    assert announce == [steps[-2][0]]


def test_the_scheduler_starts_only_after_the_database_switch():
    steps = {n: body for k, n, _, body in _steps() if k == "L"}
    switch = min(n for n, b in steps.items() if "AGENTX_DB_ENV=/etc/agentx/db.env" in b)
    start = min(n for n, b in steps.items() if "--profile scheduler up -d scheduler" in b)
    dns = min(n for n, b in steps.items() if "A 2.25.235.174" in b)
    merge = min(n for n, b in steps.items() if "Create a merge commit" in b)
    workflow_off = min(n for n, b in steps.items() if "disabled manually" in b)
    assert switch < merge < start
    assert workflow_off < merge < dns


_SECRET_LOOKING = [
    re.compile(r"pypi-[A-Za-z0-9_-]{20,}"),
    re.compile(r"npm_[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s<]+@"),
    re.compile(r"\b[0-9a-f]{32,}\b"),
    re.compile(r"ntfy\.sh/agentx-[0-9a-f]{6,}"),
    re.compile(r"hooks\.slack\.com/services/\w+"),
]


def test_no_secret_looking_strings():
    text = _text()
    for pattern in _SECRET_LOOKING:
        assert not pattern.search(text), pattern.pattern
