"""
Every seed and runner names a founder by the same DID: did:agentx:<name>-001.

Sprint 9, S9-10. The seeds used to disagree (init-db.sql had marcus-002 …
gia-008, the runners <name>-001, the post seeder <name>-seed-001 plus a
``--variant`` switch for "a fresh cohort"), and each disagreement registered a
founder a second time. scripts/dedupe_founders.py cleans that up; this test
keeps it from coming back.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_PLATFORM = Path(__file__).resolve().parents[1]
_REPO = _PLATFORM.parent

FOUNDERS = ("atlas", "bruno", "daria", "gia", "marcus", "nova", "quinn", "thea")
CANONICAL = {f"did:agentx:{name}-001" for name in FOUNDERS}

_FOUNDER_DID = re.compile(r"did:agentx:(?:%s)(?:-[a-z]+)?-[0-9]{3}" % "|".join(FOUNDERS))

# (file, whether it spells out all eight)
_SOURCES = [
    (_PLATFORM / "scripts" / "init-db.sql", True),
    (_PLATFORM / "scripts" / "seed_agents.py", True),
    (_PLATFORM / "scripts" / "seed_platform_posts.py", False),
    (_REPO / "runners" / "register_all.py", True),
    (_REPO / "runners" / "sdk_agent_runner.py", True),
    (_REPO / "runners" / "fund_wallets.py", False),
    (_REPO / "runners" / "task_seeder.py", False),
    (_REPO / "runners" / "run_atlas_sdk.py", False),
    (_REPO / "runners" / "start_all.sh", False),
    (_REPO / "scripts" / "seed_ecosystem.py", True),
    (_REPO / "agents" / "runner.py", True),
    (_REPO / "agents" / "platform_bridge.py", True),
    (_REPO / "README.md", True),
]


@pytest.mark.parametrize("path,lists_all", _SOURCES, ids=lambda v: v.name if isinstance(v, Path) else "")
def test_seed_source_uses_the_canonical_founder_dids(path: Path, lists_all: bool):
    if not path.exists():
        pytest.skip(f"{path} is not in this checkout")
    found = set(_FOUNDER_DID.findall(path.read_text()))
    assert found <= CANONICAL, f"{path.name} names a founder by another DID: {sorted(found - CANONICAL)}"
    if lists_all:
        assert found == CANONICAL, f"{path.name} is missing {sorted(CANONICAL - found)}"


def test_the_post_seeder_cannot_register_a_second_cohort():
    text = (_PLATFORM / "scripts" / "seed_platform_posts.py").read_text()
    assert 'DEFAULT_DID_SUFFIX = "-001"' in text
    assert "add_argument(\n        \"--variant\"" not in text and '"--variant"' not in text
    # A seed script must not point at production unless told to.
    assert 'default="https://' not in text


def test_runners_build_founder_dids_from_the_same_names():
    fund = (_REPO / "runners" / "fund_wallets.py")
    start = (_REPO / "runners" / "start_all.sh")
    if not fund.exists():
        pytest.skip("runners/ is not in this checkout")
    assert 'f"did:agentx:{name}-001"' in fund.read_text()
    for name in FOUNDERS:
        assert f'"{name}"' in fund.read_text()
    assert "-001\"" in start.read_text()
