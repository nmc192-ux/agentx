"""
Guard: each Fly process group gets its own machine size.

`platform/fly.toml` runs two process groups (`app`, `scheduler`) under one
shared `[[vm]]` (shared-cpu-2x, 512 MB). The scheduler is one Celery worker
with beat at concurrency 1 and needs only shared-cpu-1x, 512 MB.

The engine may not edit the Fly config files (standing rule 6), so DrJ makes
the edit (HUMAN_ACTIONS H23, Sprint 13 T-2). Until then the production check
is xfail; once the blocks are in it passes, and the marker can be removed so
it becomes a hard guard like test_fly_release_command.py.

`fly.staging.toml` has no [processes] (staging runs the API only) and one
shared-cpu-1x [[vm]], so it needs no change.
"""
import tomllib
from pathlib import Path

import pytest

_PLATFORM = Path(__file__).resolve().parent.parent

_WANTED = {
    "app": ("shared-cpu-2x", "512mb"),
    "scheduler": ("shared-cpu-1x", "512mb"),
}

# The exact text H23 tells DrJ to paste in place of the single [[vm]] block.
H23_VM_BLOCKS = """\
[[vm]]
  processes = ["app"]
  size      = "shared-cpu-2x"
  memory    = "512mb"

[[vm]]
  processes = ["scheduler"]
  size      = "shared-cpu-1x"
  memory    = "512mb"
"""

_OLD_VM_BLOCK = """\
[[vm]]
  size   = "shared-cpu-2x"
  memory = "512mb"
"""


def _sizes_by_process(config: dict) -> dict[str, tuple[str, str]]:
    """Map each process group to the (size, memory) of the [[vm]] naming it."""
    sizes: dict[str, tuple[str, str]] = {}
    for vm in config.get("vm", []):
        for group in vm.get("processes", []):
            assert group not in sizes, f"process group {group!r} in two [[vm]] blocks"
            sizes[group] = (vm.get("size"), vm.get("memory"))
    return sizes


def _check_per_process_sizes(config: dict) -> None:
    groups = set(config.get("processes", {}))
    assert groups == set(_WANTED), f"unexpected process groups {sorted(groups)}"
    assert _sizes_by_process(config) == _WANTED
    # A [[vm]] without `processes` applies to every group and would hide a mismatch.
    assert all(vm.get("processes") for vm in config.get("vm", []))


@pytest.mark.xfail(reason="waiting on DrJ's fly.toml edit (HUMAN_ACTIONS H23)", strict=False)
def test_production_sizes_each_process_group():
    _check_per_process_sizes(tomllib.loads((_PLATFORM / "fly.toml").read_text()))


def test_h23_blocks_give_the_wanted_sizes():
    """The blocks H23 asks DrJ to paste make the production check pass."""
    text = (_PLATFORM / "fly.toml").read_text()
    if _OLD_VM_BLOCK not in text:
        pytest.skip("H23 edit has landed; the production check covers it")
    _check_per_process_sizes(tomllib.loads(text.replace(_OLD_VM_BLOCK, H23_VM_BLOCKS)))


def test_single_shared_vm_fails_the_check():
    config = tomllib.loads(
        '[processes]\napp = "a"\nscheduler = "s"\n' + _OLD_VM_BLOCK
    )
    with pytest.raises(AssertionError):
        _check_per_process_sizes(config)


def test_staging_runs_one_small_machine():
    config = tomllib.loads((_PLATFORM / "fly.staging.toml").read_text())
    assert "processes" not in config, "staging gained process groups; add per-group [[vm]] blocks"
    assert [(vm["size"], vm["memory"]) for vm in config["vm"]] == [("shared-cpu-1x", "512mb")]
