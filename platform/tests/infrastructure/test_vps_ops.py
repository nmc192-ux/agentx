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
TASKS = ["status", "disk-report", "disk-cleanup", "welcomes-on", "welcomes-off", "alerts-setup", "alerts-test", "import-report", "import-apply"]


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
