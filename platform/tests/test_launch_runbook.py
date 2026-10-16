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
        "051 arrive there",                       # Phase C migrations on the VPS
        "FROM faucet_claims",                     # migration 050 ran
        "/stats/economy",                         # Phase C off on the day (D13 b)
        "/markets/bounties/showcase",             # Phase C off on the day (D13 b)
        "NEXT_PUBLIC_FEATURE_COLLECTIVES",        # website Phase C flags unset
        "H38 faucet",                             # Phase C switch-on order after launch
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


# --- The early-launch runbook (PLAN EL-6) ------------------------------------
# Same shape as the 1 Nov runbook, plus N steps (the 1 Nov import, H47). It
# replaces launch_day_runbook.md for the day; the checks below pin the parts
# that differ: no Neon copy on the day, the Fly guard before the merge, the
# bootstrap between the two Deploy to VPS runs, the reserved addresses, the
# Hostinger A/AAAA change, and the import last.

_EARLY = _REPO / "platform" / "docs" / "execution" / "early_launch_runbook.md"
_EARLY_STEP = re.compile(r"^### ([PLN])(\d{2}) · ([^·]+) · ([^—]+) — (.+)$", re.M)


def _early_text() -> str:
    return _EARLY.read_text()


def _early_steps() -> list[tuple[str, int, str, str]]:
    text = _early_text()
    heads = list(_EARLY_STEP.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].split("\n---\n")[0].split("\n## ")[0]
        out.append((m.group(1), int(m.group(2)), m.group(3).strip(), body))
    return out


def _first(kind: str, needle: str) -> int:
    return min(n for k, n, _, b in _early_steps() if k == kind and needle in b)


def test_early_runbook_has_all_three_parts():
    steps = _early_steps()
    assert {k for k, *_ in steps} == {"P", "L", "N"}
    assert len([s for s in steps if s[0] == "L"]) >= 30
    assert len([s for s in steps if s[0] == "N"]) >= 6


@pytest.mark.parametrize("kind", ["P", "L", "N"])
def test_early_steps_are_numbered_in_order_without_gaps(kind):
    numbers = [n for k, n, *_ in _early_steps() if k == kind]
    assert numbers == list(range(1, len(numbers) + 1))


def test_early_every_step_has_must_see_and_a_non_empty_undo():
    for kind, n, _, body in _early_steps():
        name = f"{kind}{n:02d}"
        assert "**Run" in body, name
        assert "**You must see:**" in body, name
        assert "**If not:**" in body, name
        undo = re.search(r"\*\*Undo:\*\*\s*(.+)", body)
        assert undo and len(undo.group(1).strip()) > 5, f"{name} has no undo line"


@pytest.mark.parametrize("kind", ["L", "N"])
def test_early_times_never_go_backwards(kind):
    times = [t for k, _, t, _ in _early_steps() if k == kind]
    for t in times:
        assert re.fullmatch(r"\d{2}:\d{2}", t), t
    assert times == sorted(times)


def test_early_every_repo_path_and_script_named_exists():
    text = _early_text()
    missing = sorted(p for p in set(_REPO_PATH.findall(text)) if not (_REPO / p).exists())
    assert not missing, missing
    for name in set(re.findall(r"\bbash ([\w-]+\.sh)\b", text)):
        assert (_REPO / "deploy" / "vps" / name).is_file(), name
    db_move = (_REPO / "deploy" / "vps" / "db_move.sh").read_text()
    for sub in set(re.findall(r"bash db_move\.sh ([a-z-]+)", text)):
        assert re.search(rf"^\s*{re.escape(sub)}\)", db_move, re.M), sub
    for script in set(re.findall(r"python (scripts/[\w]+\.py)", text)):
        assert (_REPO / "platform" / script).is_file(), script


def test_early_quoted_script_output_matches_the_scripts():
    """The "must see" lines quote what the scripts print; a reworded message
    would leave DrJ looking for a line that never comes."""
    scripts = _REPO / "platform" / "scripts"
    bootstrap = (scripts / "bootstrap_db.py").read_text()
    for needle in ("OK: bootstrap complete", "seeded the base schema and 8 founders",
                   "refused: "):
        assert needle in bootstrap, needle
    deploy = (_REPO / "deploy" / "vps" / "deploy.sh").read_text()
    for needle in ("refusing to migrate: the database is empty or not an AgentX database",
                   "Nothing was replaced."):
        assert needle in deploy and needle in _early_text(), needle
    reserve = (scripts / "reserve_dids.py").read_text()
    for needle in ("address(es) reserved", "released {n} reservation(s)", "dry run: nothing written"):
        assert needle in reserve, needle
    imp = (scripts / "import_old_data.py").read_text()
    for needle in ("DRY RUN", "APPLIED", "OK: imported"):
        assert needle in imp, needle


def test_early_required_steps_are_present():
    text = _early_text()
    for needle in (
        "Disable workflow",                        # H44: Fly Deploy off
        "FLY_API_TOKEN",                           # H44: and no token to reach Fly
        "H45",                                     # VPS prep for the fresh start
        "AGENTX_DB_ENV=/etc/agentx/db.env",        # VPS database from the start
        "Deploy to VPS",                           # the only deploy
        "scripts/bootstrap_db.py",                 # EL-1
        "bootstrap_db.py --check",                 # EL-1 check
        "atlas-seed-001",                          # production founder DIDs
        "reserve_dids.py load",                    # H46 B (EL-2)
        "reserve_dids.py release --all",           # H47 step 6
        "`A` `2.25.235.174`",                      # Hostinger: api -> VPS
        "66.241.125.103",                          # the old A value it replaces
        "2a09:8280:1::108:ae41:0",                 # Fly's AAAA, deleted
        "--profile scheduler up -d scheduler",     # scheduler on
        "bash db_move.sh restore-test",            # tested restore
        "bash watchdog.sh",                        # alerts on
        "Fly-Client-IP: 203.0.113.9",              # spoofed-address check
        "/stats/economy",                          # Phase C off
        "/markets/bounties/showcase",              # Phase C off
        "NEXT_PUBLIC_FEATURE_COLLECTIVES",         # website Phase C flags unset
        "sdk-v0.4.0", "@agentx/sdk", "agentx-mcp", "clawhub",   # packages
        "scripts/import_old_data.py --old-db agentx_old",       # H47 (EL-5)
        "D14",                                     # old agents' logins
        "H38 faucet",                              # Phase C order after 1 Nov
    ):
        assert needle in text, needle


def test_early_no_neon_copy_on_launch_day():
    """The fresh start: nothing on launch day dumps, restores or compares Neon."""
    for kind, n, _, body in _early_steps():
        if kind != "L":
            continue
        for word in ("db_move.sh dump", "db_move.sh restore ", "db_move.sh verify", "pg_restore"):
            assert word not in body, f"L{n:02d}: {word}"


def test_early_order_of_the_day():
    merge = _first("L", "Create a merge commit")
    guard = _first("L", "disabled manually")
    deploy_runs = sorted(n for k, n, _, b in _early_steps()
                         if k == "L" and "Deploy to VPS" in b and "Run workflow" in b)
    bootstrap = _first("L", "python scripts/bootstrap_db.py\n")
    reserve = _first("L", "H46 part B")
    refused = _first("L", "/agents -H")
    dns = _first("L", "`A` `2.25.235.174`")
    scheduler = _first("L", "--profile scheduler up -d scheduler")
    assert guard < merge, "the Fly guard is checked before the merge"
    assert len(deploy_runs) == 2 and merge < deploy_runs[0] < bootstrap < deploy_runs[1]
    assert deploy_runs[1] < reserve < refused < dns, "addresses reserved before the public name"
    assert dns < scheduler


def test_early_bootstrap_uses_the_image_from_the_first_run():
    """compose.env has no tag until a deploy succeeds, so the bootstrap names it."""
    steps = {n: b for k, n, _, b in _early_steps() if k == "L"}
    assert "IMAGE_TAG=<hash> docker compose" in steps[_first("L", "python scripts/bootstrap_db.py\n")]


def test_early_announcement_is_last_and_import_backs_up_first():
    steps = [(n, body) for k, n, _, body in _early_steps() if k == "L"]
    announce = [n for n, body in steps if "H28" in body and "alpha_announcement" in body]
    assert announce == [steps[-2][0]]
    n_steps = [b for k, _, _, b in _early_steps() if k == "N"]
    assert "bash db_move.sh backup" in n_steps[0]
    apply_at = next(i for i, b in enumerate(n_steps) if "--apply" in b)
    dry_at = next(i for i, b in enumerate(n_steps) if "DRY RUN" in b)
    assert dry_at < apply_at


def test_early_no_phase_c_switch_is_set_on_the_day():
    for kind, n, _, body in _early_steps():
        if kind == "L":
            for key in ("FAUCET_ENABLED=", "SHOWCASE_ENABLED=", "ECONOMY_STATS_ENABLED=",
                        "TASK_WORK_DAYS=", "LEGACY_BOUNTY_DAYS=", "COLLECTIVE_MIN_PAID_JOBS="):
                assert key not in body, f"L{n:02d}: {key}"


def test_early_no_secret_looking_strings():
    text = _early_text()
    for pattern in _SECRET_LOOKING:
        assert not pattern.search(text), pattern.pattern
