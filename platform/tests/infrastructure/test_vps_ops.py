"""The "VPS ops" workflow and deploy/vps/ops.sh (DrJ, 26 Oct 2026: automate H50 step 2, H37, H47).

Rules pinned here:
  1. The workflow only runs by hand, from main, in the `production` environment, in the deploy's
     concurrency group, with read-only repository access.
  2. Only a fixed list of tasks exists, and it is the same list in the workflow and in ops.sh;
     no workflow input is expanded inside a shell script.
  3. ops.sh never uses sudo and can only write the switches it names (FOUNDER_WELCOMES_ENABLED).
  4. api.env beats ops.env: compose loads ops.env before api.env, and `welcomes` refuses when
     api.env already sets the switch.
  5. The Neon password reaches the VPS on stdin only; a new ntfy topic is masked in the log.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "vps-ops.yml"
OPS = REPO / "deploy" / "vps" / "ops.sh"
COMPOSE = REPO / "deploy" / "vps" / "docker-compose.yml"
TASKS = ["status", "heartbeat-report", "disk-report", "disk-cleanup", "build-cache-clear", "welcomes-on", "welcomes-off", "alerts-setup", "alerts-test", "import-report", "import-apply", "test-accounts-report", "test-accounts-remove"]


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _on(wf: dict) -> dict:
    return wf.get("on", wf.get(True))   # PyYAML reads the bare key `on` as True


class TestWorkflow:
    def test_manual_only_with_fixed_choices(self):
        on = _on(_wf())
        assert set(on) == {"workflow_dispatch"}
        task = on["workflow_dispatch"]["inputs"]["task"]
        assert task["type"] == "choice"
        assert task["options"] == TASKS
        assert set(on["workflow_dispatch"]["inputs"]) == {"task"}

    def test_main_production_shared_lock_read_only(self):
        wf = _wf()
        assert wf["permissions"] == {}
        assert wf["concurrency"] == {"group": "deploy-vps", "cancel-in-progress": False}
        job = wf["jobs"]["ops"]
        assert job["if"] == "github.ref == 'refs/heads/main'"
        assert job["environment"]["name"] == "production"
        assert job["permissions"] == {"contents": "read"}

    def test_inputs_never_expanded_inside_scripts(self):
        for step in _wf()["jobs"]["ops"]["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")

    def test_task_list_matches_ops_sh(self):
        text = OPS.read_text()
        for task in TASKS:
            name = task.split("-on")[0].split("-off")[0]
            assert re.search(rf"^\s+{re.escape(name)}\)", text, re.M), task

    def test_neon_password_on_stdin_and_topic_masked(self):
        run = next(s["run"] for s in _wf()["jobs"]["ops"]["steps"] if s.get("name") == "Run the task")
        assert "printf '%s\\n' \"$NEON_PASSWORD\" | $SSH" in run
        assert "NEON_PASSWORD=" not in run.split("| $SSH", 1)[1].split("\n", 1)[0]
        assert run.index("::add-mask::$TOPIC") < run.index("grep -v '^NTFY_TOPIC=' \"$OUT\" || true")

    def test_ssh_key_removed_always(self):
        last = _wf()["jobs"]["ops"]["steps"][-1]
        assert last["if"] == "always()" and "rm -rf \"$RUNNER_TEMP/ssh\"" in last["run"]


class TestOpsScript:
    def test_no_sudo_and_one_switch(self):
        text = OPS.read_text()
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert "sudo" not in code
        assert re.search(r'^OPS_SWITCHES="FOUNDER_WELCOMES_ENABLED"$', text, re.M)

    def test_bash_syntax(self):
        subprocess.run(["bash", "-n", str(OPS)], check=True)

    def test_compose_loads_ops_env_optional_before_api_env(self):
        compose = yaml.safe_load(COMPOSE.read_text())
        files = compose["services"]["api-1"]["env_file"]
        paths = [f["path"] for f in files]
        ops = paths.index("${AGENTX_OPS_ENV:-./ops.env}")
        assert ops == paths.index("./settings.env") + 1
        assert ops < paths.index("${AGENTX_SECRETS_FILE:-/etc/agentx/api.env}")
        assert files[ops]["required"] is False


def _fake_bin(tmp: Path) -> Path:
    """docker and crontab stand-ins: every container is healthy, nothing really runs."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$FAKE_LOG"\n'
        'case "$*" in\n'
        '  *"ps -q"*) echo abc123 ;;\n'
        '  inspect*) echo healthy ;;\n'
        '  *printenv*) sed -n "s/^FOUNDER_WELCOMES_ENABLED=//p" "$AGENTX_OPS_ENV" ;;\n'
        "esac\n"
    )
    (bin_dir / "crontab").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run(tmp: Path, *args: str, api_env: str = "FOUNDER_HEARTBEAT_ENABLED=true\n") -> subprocess.CompletedProcess:
    (tmp / "compose.env").write_text("IMAGE_TAG=abc\n")
    (tmp / "api.env").write_text(api_env)
    env = {
        **os.environ,
        "PATH": f"{_fake_bin(tmp) if not (tmp / 'bin').exists() else tmp / 'bin'}:{os.environ['PATH']}",
        "AGENTX_DIR": str(tmp),
        "AGENTX_OPS_ENV": str(tmp / "ops.env"),
        "AGENTX_SECRETS_FILE": str(tmp / "api.env"),
        "FAKE_LOG": str(tmp / "docker.log"),
    }
    return subprocess.run(["bash", str(OPS), *args], env=env, capture_output=True, text=True)


class TestWelcomes:
    def test_on_then_off_rolls_one_at_a_time(self, tmp_path):
        result = _run(tmp_path, "welcomes", "on")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "ops.env").read_text().splitlines()[-1] == "FOUNDER_WELCOMES_ENABLED=true"
        assert oct((tmp_path / "ops.env").stat().st_mode & 0o777) == "0o600"
        assert "api-1 sees FOUNDER_WELCOMES_ENABLED=true" in result.stdout
        log = (tmp_path / "docker.log").read_text()
        assert log.index("--force-recreate api-1") < log.index("--force-recreate api-2")

        result = _run(tmp_path, "welcomes", "off")
        assert result.returncode == 0, result.stderr
        lines = [s for s in (tmp_path / "ops.env").read_text().splitlines() if not s.startswith("#")]
        assert lines == ["FOUNDER_WELCOMES_ENABLED=false"]

    def test_refuses_when_api_env_sets_it(self, tmp_path):
        result = _run(tmp_path, "welcomes", "on", api_env="FOUNDER_WELCOMES_ENABLED=false\n")
        assert result.returncode != 0
        assert "change it there" in result.stderr
        assert not (tmp_path / "ops.env").exists()

    def test_unknown_task_refused(self, tmp_path):
        assert _run(tmp_path, "rm-everything").returncode == 2

    @pytest.mark.parametrize("value", ["maybe", "true", ""])
    def test_bad_value_refused(self, tmp_path, value):
        assert _run(tmp_path, "welcomes", value).returncode != 0


CUR, PREV, OLD = "a" * 40, "b" * 40, "c" * 40
REPO_IMG = "ghcr.io/nmc192-ux/agentx-platform"


class TestDiskCleanup:
    def _setup(self, tmp: Path) -> dict:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(
            "#!/usr/bin/env bash\n"
            'echo "$*" >> "$FAKE_LOG"\n'
            'case "$1 $2" in\n'
            f'  "images --format") printf "{REPO_IMG}:{CUR}\\n{REPO_IMG}:{PREV}\\n{REPO_IMG}:{OLD}\\n" ;;\n'
            '  "image prune") echo "Total reclaimed space: 0B" ;;\n'
            "esac\n"
        )
        (bin_dir / "docker").chmod(0o755)
        (tmp / "compose.env").write_text(f"AGENTX_IMAGE={REPO_IMG}\nIMAGE_TAG={CUR}\n")
        (tmp / "status").mkdir()
        (tmp / "status" / "deploy.json").write_text(f'{{"commit": "{CUR}", "previous": "{PREV}"}}\n')
        return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AGENTX_DIR": str(tmp),
                "FAKE_LOG": str(tmp / "docker.log"), "BACKUP_DIR": str(tmp)}

    def test_keeps_running_and_previous_removes_only_old_agentx(self, tmp_path):
        env = self._setup(tmp_path)
        r = subprocess.run(["bash", str(OPS), "disk-cleanup"], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        rmi = [line for line in (tmp_path / "docker.log").read_text().splitlines() if line.startswith("rmi")]
        assert rmi == [f"rmi {REPO_IMG}:{OLD}"]
        log = (tmp_path / "docker.log").read_text()
        assert "image prune -f" in log and "-a" not in log.split("image prune", 1)[1].splitlines()[0]
        assert "system prune" not in log and "volume" not in log and "builder" not in log

    def test_refuses_without_agentx_image(self, tmp_path):
        env = self._setup(tmp_path)
        (tmp_path / "compose.env").write_text("IMAGE_TAG=abc\n")
        r = subprocess.run(["bash", str(OPS), "disk-cleanup"], env=env, capture_output=True, text=True)
        assert r.returncode != 0 and "nothing removed" in r.stderr
        assert "rmi" not in (tmp_path / "docker.log").read_text() if (tmp_path / "docker.log").exists() else True


class TestBuildCacheClear:
    def test_only_prunes_the_build_cache(self, tmp_path):
        env = TestDiskCleanup()._setup(tmp_path)
        r = subprocess.run(["bash", str(OPS), "build-cache-clear"], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        log = (tmp_path / "docker.log").read_text().splitlines()
        changes = [c for c in log if not c.startswith("system df")]
        assert changes == ["builder prune -a -f"]


class TestNeonPasswordFile:
    def test_failed_dump_leaves_no_password_file(self, tmp_path):
        env = TestDiskCleanup()._setup(tmp_path)
        (tmp_path / "db_move.sh").write_text(
            '#!/usr/bin/env bash\n[ "$1" = backup ] && exit 0\n'
            'grep -q "^POSTGRES_PASSWORD=s3cret$" "$AGENTX_SECRETS_FILE" || exit 9\nexit 1\n'
        )
        (tmp_path / ".neon.env.OLD123").write_text("POSTGRES_PASSWORD=left-from-before\n")
        env["NEON_HOST"] = "ep-cool-name-123456.us-east-1.aws.neon.tech"
        r = subprocess.run(["bash", str(OPS), "import-report"], env=env, input="s3cret\n",
                           capture_output=True, text=True)
        assert r.returncode != 0
        assert "unbound variable" not in r.stderr
        assert not list(tmp_path.glob(".neon.env.*"))

    def test_any_task_sweeps_a_leftover_file(self, tmp_path):
        env = TestDiskCleanup()._setup(tmp_path)
        (tmp_path / ".neon.env.OLD123").write_text("POSTGRES_PASSWORD=x\n")
        subprocess.run(["bash", str(OPS), "disk-cleanup"], env=env, capture_output=True, text=True)
        assert not list(tmp_path.glob(".neon.env.*"))

    @pytest.mark.parametrize("pasted", [
        "s3cret", " s3cret \r", '"s3cret"', "'s3cret'",
        "postgresql://neondb_owner:s3cret@ep-cool-name-123456.us-east-1.aws.neon.tech/neondb?sslmode=require",
    ])
    def test_pasted_password_is_cleaned(self, tmp_path, pasted):
        env = TestDiskCleanup()._setup(tmp_path)
        # db_move.sh stand-in: exit 0 only when the file holds exactly the clean password.
        (tmp_path / "db_move.sh").write_text(
            '#!/usr/bin/env bash\n[ "$1" = backup ] && exit 0\n'
            'grep -qx "POSTGRES_PASSWORD=s3cret" "$AGENTX_SECRETS_FILE" && exit 42 || exit 9\n'
        )
        env["NEON_HOST"] = "ep-cool-name-123456.us-east-1.aws.neon.tech"
        r = subprocess.run(["bash", str(OPS), "import-report"], env=env, input=pasted + "\n",
                           capture_output=True, text=True)
        assert r.returncode == 42, (r.stdout, r.stderr)
        assert "s3cret" not in r.stdout + r.stderr
        assert "6 characters" in r.stdout and "ep-cool-name-123456" in r.stdout


A = "did:agentx:canary-aaa111-001"
B = "did:agentx:sdk-canary-bbb222-001"
DRY_RUN = (
    "Test accounts to remove: 2\n"
    f"  {A}  'canary-x'  MEMBER ACTIVE  signed up 2026-04-02\n"
    "      own rows deleted: posts 1\n"
    f"  {B}  'sdk-canary-y'  MEMBER ACTIVE  signed up 2026-04-03\n"
    "      own rows deleted: none\n"
    "DRY RUN: 2 test account(s) would be removed. Nothing was changed; add --apply to write.\n"
)


class TestTestAccounts:
    """H25 as two VPS ops tasks (Layer 1 S1-4): report keeps the dry run's list; remove takes a
    backup and removes exactly that list, once, within a day; anything off removes nothing."""

    def _setup(self, tmp: Path, dry_run: str = DRY_RUN, dry_exit: int = 0) -> dict:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (tmp / "dry.txt").write_text(dry_run)
        (bin_dir / "docker").write_text(
            "#!/usr/bin/env bash\n"
            'echo "$*" >> "$FAKE_LOG"\n'
            'case "$*" in\n'
            '  *"vps_test_accounts.py show"*) echo "Test accounts: 2" ;;\n'
            '  *"vps_test_accounts.py remove"*--apply*) echo "Written to the database: 2 test account(s) removed." ;;\n'
            f'  *"vps_test_accounts.py remove") cat "$AGENTX_DIR/dry.txt"; exit {dry_exit} ;;\n'
            "esac\n"
        )
        (bin_dir / "docker").chmod(0o755)
        (tmp / "db_move.sh").write_text('#!/usr/bin/env bash\necho "db_move $*" >> "$FAKE_LOG"\n')
        (tmp / "compose.env").write_text("IMAGE_TAG=abc\n")
        return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AGENTX_DIR": str(tmp),
                "FAKE_LOG": str(tmp / "docker.log")}

    def _ops(self, env: dict, task: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(OPS), task], env=env, capture_output=True, text=True)

    def _log(self, tmp: Path) -> list[str]:
        f = tmp / "docker.log"
        return f.read_text().splitlines() if f.exists() else []

    def test_report_changes_nothing_and_keeps_the_list(self, tmp_path):
        env = self._setup(tmp_path)
        r = self._ops(env, "test-accounts-report")
        assert r.returncode == 0, r.stderr
        assert "DRY RUN: 2" in r.stdout
        assert not any("--apply" in c or c.startswith("db_move") for c in self._log(tmp_path))
        kept = tmp_path / "test_accounts.dids"
        assert kept.read_text().splitlines() == [A, B]
        assert stat.S_IMODE(kept.stat().st_mode) == 0o600

    def test_remove_backs_up_then_removes_exactly_the_list_once(self, tmp_path):
        env = self._setup(tmp_path)
        assert self._ops(env, "test-accounts-report").returncode == 0
        r = self._ops(env, "test-accounts-remove")
        assert r.returncode == 0, r.stderr
        log = self._log(tmp_path)
        backup = log.index("db_move backup")
        (apply,) = [i for i, c in enumerate(log) if "--apply" in c]
        assert backup < apply
        assert log[apply].endswith(
            f"python scripts/vps_test_accounts.py remove --did {A} --did {B} --apply --by DrJ (VPS ops)")
        assert "show" in log[-1]
        assert not (tmp_path / "test_accounts.dids").exists()
        again = self._ops(env, "test-accounts-remove")           # used once
        assert again.returncode != 0 and "run it first" in again.stderr
        assert sum("--apply" in c for c in self._log(tmp_path)) == 1

    def test_remove_without_a_report_does_nothing(self, tmp_path):
        env = self._setup(tmp_path)
        r = self._ops(env, "test-accounts-remove")
        assert r.returncode != 0 and "test-accounts-report" in r.stderr
        assert self._log(tmp_path) == []

    def test_remove_refuses_an_old_list(self, tmp_path):
        env = self._setup(tmp_path)
        assert self._ops(env, "test-accounts-report").returncode == 0
        kept = tmp_path / "test_accounts.dids"
        old = kept.stat().st_mtime - 25 * 3600
        os.utime(kept, (old, old))
        before = self._log(tmp_path)
        r = self._ops(env, "test-accounts-remove")
        assert r.returncode != 0 and "older than 24 hours" in r.stderr
        assert self._log(tmp_path) == before and not kept.exists()

    @pytest.mark.parametrize("line", [
        "did:agentx:x; rm -rf /", "--apply", "did:agentx:a b", "", "did:other:abc",
    ])
    def test_remove_refuses_a_damaged_list(self, tmp_path, line):
        env = self._setup(tmp_path)
        (tmp_path / "test_accounts.dids").write_text(f"{A}\n{line}\n")
        r = self._ops(env, "test-accounts-remove")
        assert r.returncode != 0 and "damaged" in r.stderr
        assert self._log(tmp_path) == []

    def test_refused_dry_run_keeps_no_list(self, tmp_path):
        env = self._setup(tmp_path, dry_run="", dry_exit=1)
        (tmp_path / "test_accounts.dids").write_text(f"{A}\n")      # left from an earlier report
        r = self._ops(env, "test-accounts-report")
        assert r.returncode != 0 and "refused" in r.stderr
        assert not (tmp_path / "test_accounts.dids").exists()

    def test_count_mismatch_keeps_no_list(self, tmp_path):
        env = self._setup(tmp_path, dry_run=DRY_RUN.replace("DRY RUN: 2", "DRY RUN: 3"))
        r = self._ops(env, "test-accounts-report")
        assert r.returncode != 0 and "does not match" in r.stderr
        assert not list(tmp_path.glob("test_accounts.dids*"))

    def test_nothing_to_remove_keeps_no_list(self, tmp_path):
        env = self._setup(tmp_path, dry_run="No test accounts found; nothing to remove.\n")
        r = self._ops(env, "test-accounts-report")
        assert r.returncode == 0 and "nothing to remove" in r.stdout
        assert not list(tmp_path.glob("test_accounts.dids*"))

    def test_image_carries_both_scripts(self):
        dockerfile = (REPO / "platform" / "Dockerfile.fly").read_text()
        for name in ("remove_test_accounts.py", "vps_test_accounts.py"):
            assert f"COPY scripts/{name} ./scripts/{name}" in dockerfile

    def test_unreadable_dry_run_keeps_no_list(self, tmp_path):
        """S1-8 review: if the dry run says N would be removed but its address lines can't be
        read (a format change), the report must fail rather than say "nothing to remove"."""
        env = self._setup(tmp_path, dry_run=DRY_RUN.replace(f"  {A}  ", f" {A} ").replace(f"  {B}  ", f" {B} "))
        r = self._ops(env, "test-accounts-report")
        assert r.returncode != 0 and "no address could be read" in r.stderr
        assert not list(tmp_path.glob("test_accounts.dids*"))
        assert not any("--apply" in c for c in self._log(tmp_path))

    def test_one_odd_address_refuses_the_whole_report(self, tmp_path):
        """S1-8 review: an address the parser cannot read is never silently dropped; the count
        check refuses the report and keeps no list."""
        env = self._setup(tmp_path, dry_run=DRY_RUN.replace(B, "did:agentx:odd/char-001"))
        r = self._ops(env, "test-accounts-report")
        assert r.returncode != 0 and "does not match the 1 addresses" in r.stderr
        assert not list(tmp_path.glob("test_accounts.dids*"))

    def test_display_name_cannot_smuggle_an_address(self, tmp_path):
        """S1-8 review: a display name is printed with repr() on the same line as its own
        address, so text in it that looks like another address or a DRY RUN line changes
        nothing: only the two real addresses are kept."""
        evil = "'x  did:agentx:victim-000  MEMBER ACTIVE\\nDRY RUN: 3 test account(s) would be removed.'"
        env = self._setup(tmp_path, dry_run=DRY_RUN.replace("'canary-x'", evil))
        r = self._ops(env, "test-accounts-report")
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "test_accounts.dids").read_text().splitlines() == [A, B]

    def test_extra_address_line_refuses_the_report(self, tmp_path):
        """S1-8 review: an address line the dry run did not count (noise printed before the
        report, say) makes the count check refuse; nothing is kept."""
        env = self._setup(tmp_path, dry_run=f"  did:agentx:extra-000  'noise'  x\n{DRY_RUN}")
        r = self._ops(env, "test-accounts-report")
        assert r.returncode != 0 and "does not match the 3 addresses" in r.stderr
        assert not list(tmp_path.glob("test_accounts.dids*"))

    def test_script_runs_without_a_pseudo_terminal(self, tmp_path):
        """S1-8 review: every call goes through `compose run -T`, so a hand run from an SSH
        terminal gives the same stdout (no CR endings, no merged stderr) as the workflow."""
        env = self._setup(tmp_path)
        assert self._ops(env, "test-accounts-report").returncode == 0
        assert self._ops(env, "test-accounts-remove").returncode == 0
        calls = [c for c in self._log(tmp_path) if "vps_test_accounts.py" in c]
        assert len(calls) == 4
        assert all(" run --rm -T migrate python scripts/vps_test_accounts.py" in c for c in calls)


class TestVpsTestAccountsWrapper:
    """S1-8 review of scripts/vps_test_accounts.py: the command comes first, so no option (and no
    argparse abbreviation of --dsn such as --ds or --d) can point the reviewed script at another
    database; anything else exits 2 before the app settings are even read."""

    @pytest.fixture
    def wrapper(self, monkeypatch):
        import importlib.util
        scripts = REPO / "platform" / "scripts"
        monkeypatch.syspath_prepend(str(scripts))
        spec = importlib.util.spec_from_file_location("vps_test_accounts", scripts / "vps_test_accounts.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.fixture
    def settings_calls(self, monkeypatch):
        import src.config as config
        calls = []

        class Stub:
            postgres_host, postgres_port, postgres_user = "127.0.0.1", 1, "u"
            postgres_password, postgres_db, postgres_ssl_mode = "pw-never-shown", "d", "disable"

        def fake():
            calls.append(1)
            return Stub()
        monkeypatch.setattr(config, "get_settings", fake)
        for k in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE"):
            monkeypatch.delenv(k, raising=False)
        yield calls
        for k in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE"):
            os.environ.pop(k, None)

    @pytest.mark.parametrize("argv", [
        [], ["--help"],
        ["--dsn", "postgresql://127.0.0.1:1/x", "show"], ["--dsn=postgresql://127.0.0.1:1/x", "show"],
        ["--ds", "postgresql://127.0.0.1:1/x", "show"], ["--d", "postgresql://127.0.0.1:1/x", "remove"],
        ["show", "--dsn", "postgresql://127.0.0.1:1/x"], ["remove", "--dsn=postgresql://127.0.0.1:1/x"],
        ["remove", "--max", "5", "--dsn", "postgresql://127.0.0.1:1/x", "--apply"],
        ["status"], ["remove-all"],
    ])
    def test_refused_before_settings_are_read(self, wrapper, settings_calls, argv, capsys):
        assert wrapper.main(argv) == 2
        assert settings_calls == []
        assert "PGPASSWORD" not in os.environ
        assert "vps_test_accounts:" in capsys.readouterr().err

    @pytest.mark.parametrize("argv", [
        ["remove", "--ds", "postgresql://127.0.0.1:1/x"], ["show", "--ds", "postgresql://127.0.0.1:1/x"],
        ["remove", "--max", "5", "--ds=postgresql://127.0.0.1:1/x", "--apply"],
    ])
    def test_dsn_after_the_command_is_rejected_by_the_script(self, wrapper, settings_calls, argv, capsys):
        """After the command the reviewed script's parser knows no --dsn (nor an abbreviation):
        it exits 2 without connecting anywhere."""
        with pytest.raises(SystemExit) as e:
            wrapper.main(argv)
        assert e.value.code == 2
        assert "pw-never-shown" not in capsys.readouterr().err
