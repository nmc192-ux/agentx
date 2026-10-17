"""
agentx-social — the identity file holds live credentials (Sprint 14 security review).

* ``AgentIdentity.save`` writes mode 0600 through a private temp file and one
  atomic rename; nothing half-written or world-readable ever exists at the path;
* a symlink planted at the path is replaced, never written through;
* ``load`` tightens a group/world-readable file to 0600 with a warning (files
  written by older SDK versions were 0644), refuses it when that is impossible,
  and judges a symlink by its target;
* ``AgentXClient.onboard(identity_path=...)`` refuses to overwrite an existing
  file before any request is sent, unless ``overwrite_identity=True``;
* the file is saved again after every token refresh.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys

import httpx
import pytest
import respx

from agentx_sdk import AgentIdentity, AgentXClient

from .test_onboard import ACCESS, ACCESS2, BASE, DID, ONBOARD_BODY, PAIR_BODY, REFRESH, REFRESH2

posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def _mode(p: pathlib.Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@posix
def test_save_writes_0600_regardless_of_umask(tmp_path: pathlib.Path):
    path = tmp_path / "identity.json"
    old = os.umask(0o000)
    try:
        AgentIdentity(agent_did=DID, api_key=ACCESS, refresh_token=REFRESH).save(str(path))
    finally:
        os.umask(old)
    assert _mode(path) == 0o600
    assert json.loads(path.read_text())["refresh_token"] == REFRESH
    assert sorted(p.name for p in tmp_path.iterdir()) == ["identity.json"], "no temp file left"


@posix
def test_save_replaces_an_existing_file_atomically_and_keeps_it_private(tmp_path: pathlib.Path):
    path = tmp_path / "identity.json"
    path.write_text("old")
    path.chmod(0o644)
    AgentIdentity(agent_did=DID, api_key=ACCESS2).save(str(path))
    assert _mode(path) == 0o600
    assert json.loads(path.read_text())["api_key"] == ACCESS2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["identity.json"]


def test_save_replaces_a_planted_symlink_instead_of_writing_through_it(tmp_path: pathlib.Path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n")
    path = tmp_path / "identity.json"
    path.symlink_to(victim)
    AgentIdentity(agent_did=DID, api_key=ACCESS).save(str(path))
    assert victim.read_text() == "keep me\n"
    assert not path.is_symlink()
    assert AgentIdentity.load(str(path)).api_key == ACCESS


def test_save_leaves_nothing_behind_when_the_directory_is_missing(tmp_path: pathlib.Path):
    path = tmp_path / "gone" / "identity.json"
    with pytest.raises(OSError):
        AgentIdentity(agent_did=DID, api_key=ACCESS).save(str(path))
    assert list(tmp_path.iterdir()) == []


def test_save_refuses_an_identity_without_did_or_token(tmp_path: pathlib.Path):
    with pytest.raises(ValueError):
        AgentIdentity(agent_did="", api_key=ACCESS).save(str(tmp_path / "x.json"))
    with pytest.raises(ValueError):
        AgentIdentity(agent_did=DID, api_key="").save(str(tmp_path / "x.json"))
    assert list(tmp_path.iterdir()) == []


@posix
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660, 0o666, 0o777])
def test_load_tightens_a_readable_file_to_0600_with_a_warning(tmp_path: pathlib.Path, mode: int):
    path = tmp_path / "identity.json"
    path.write_text(json.dumps({"agent_did": DID, "api_key": ACCESS, "refresh_token": REFRESH}))
    path.chmod(mode)
    with pytest.warns(RuntimeWarning, match="changed to 0600"):
        loaded = AgentIdentity.load(str(path))
    assert loaded.api_key == ACCESS
    assert _mode(path) == 0o600


@posix
def test_load_is_quiet_for_a_private_file(tmp_path: pathlib.Path, recwarn):
    path = tmp_path / "identity.json"
    AgentIdentity(agent_did=DID, api_key=ACCESS).save(str(path))
    assert AgentIdentity.load(str(path)).agent_did == DID
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


@posix
def test_load_refuses_a_readable_file_it_cannot_make_private(tmp_path: pathlib.Path, monkeypatch):
    path = tmp_path / "identity.json"
    path.write_text(json.dumps({"agent_did": DID, "api_key": ACCESS}))
    path.chmod(0o644)

    def deny(fd, mode):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "fchmod", deny)
    with pytest.raises(PermissionError, match="chmod 600"):
        AgentIdentity.load(str(path))
    assert _mode(path) == 0o644, "nothing else changed"


@posix
def test_load_judges_a_symlink_by_its_target(tmp_path: pathlib.Path):
    target = tmp_path / "shared.json"
    target.write_text(json.dumps({"agent_did": DID, "api_key": ACCESS}))
    target.chmod(0o644)
    link = tmp_path / "identity.json"
    link.symlink_to(target)
    with pytest.warns(RuntimeWarning):
        assert AgentIdentity.load(str(link)).api_key == ACCESS
    assert _mode(target) == 0o600


def test_load_refuses_a_directory_bad_json_and_missing_fields(tmp_path: pathlib.Path):
    with pytest.raises((IsADirectoryError, ValueError)):
        AgentIdentity.load(str(tmp_path))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    bad.chmod(0o600)
    with pytest.raises(ValueError, match="valid JSON"):
        AgentIdentity.load(str(bad))
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"agent_did": DID}))
    empty.chmod(0o600)
    with pytest.raises(ValueError, match="agent_did or api_key"):
        AgentIdentity.load(str(empty))
    with pytest.raises(FileNotFoundError):
        AgentIdentity.load(str(tmp_path / "nope.json"))
    assert AgentIdentity.load_or_none(str(tmp_path / "nope.json")) is None


def test_round_trip_keeps_every_field(tmp_path: pathlib.Path):
    path = tmp_path / "identity.json"
    AgentIdentity(
        agent_did=DID, api_key=ACCESS, display_name="Atlas", owner_id="owner-7", refresh_token=REFRESH,
    ).save(str(path))
    loaded = AgentIdentity.load(str(path))
    assert loaded == AgentIdentity(
        agent_did=DID, api_key=ACCESS, display_name="Atlas", owner_id="owner-7", refresh_token=REFRESH,
    )


# ── Through the client ───────────────────────────────────────────────────────

@respx.mock
def test_onboard_refuses_to_overwrite_an_identity_file_before_sending_anything(tmp_path: pathlib.Path):
    route = respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(201, json=ONBOARD_BODY))
    path = tmp_path / "identity.json"
    AgentIdentity(agent_did="did:agentx:other", api_key="other-token").save(str(path))
    with pytest.raises(FileExistsError, match="already exists"):
        AgentXClient.onboard("MyBot", base_url=BASE, identity_path=str(path))
    assert route.call_count == 0, "no agent must be minted when the save would be refused"
    assert json.loads(path.read_text())["agent_did"] == "did:agentx:other"

    # A dangling symlink counts as existing too.
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "missing.json")
    with pytest.raises(FileExistsError):
        AgentXClient.onboard("MyBot", base_url=BASE, identity_path=str(dangling))
    assert route.call_count == 0


@respx.mock
def test_onboard_overwrites_when_told_to(tmp_path: pathlib.Path):
    respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(201, json=ONBOARD_BODY))
    path = tmp_path / "identity.json"
    AgentIdentity(agent_did="did:agentx:other", api_key="other-token").save(str(path))
    client = AgentXClient.onboard("MyBot", base_url=BASE, identity_path=str(path), overwrite_identity=True)
    client.close()
    saved = json.loads(path.read_text())
    assert saved["agent_did"] == DID and saved["api_key"] == ACCESS
    if sys.platform != "win32":
        assert _mode(path) == 0o600


@respx.mock
def test_refresh_saves_the_identity_file_again(tmp_path: pathlib.Path):
    respx.post(f"{BASE}/auth/token").mock(return_value=httpx.Response(200, json=PAIR_BODY))
    respx.get(f"{BASE}/agents/{DID}").mock(return_value=httpx.Response(200, json={}))
    path = tmp_path / "identity.json"
    AgentIdentity(agent_did=DID, api_key=ACCESS, display_name="Atlas", owner_id="o", refresh_token=REFRESH).save(str(path))
    client = AgentXClient("", base_url=BASE, identity_path=str(path), expires_in=0)
    client._get(f"/agents/{DID}")
    client.close()
    saved = json.loads(path.read_text())
    assert saved["api_key"] == ACCESS2
    assert saved["refresh_token"] == REFRESH2
    assert saved["agent_did"] == DID
    assert saved["display_name"] == "Atlas" and saved["owner_id"] == "o"
    if sys.platform != "win32":
        assert _mode(path) == 0o600


@respx.mock
def test_refresh_without_an_identity_file_writes_nothing(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    respx.post(f"{BASE}/auth/token").mock(return_value=httpx.Response(200, json=PAIR_BODY))
    respx.get(f"{BASE}/agents/{DID}").mock(return_value=httpx.Response(200, json={}))
    client = AgentXClient(ACCESS, base_url=BASE, refresh_token=REFRESH, expires_in=0)
    client._get(f"/agents/{DID}")
    client.close()
    assert list(tmp_path.iterdir()) == []


@respx.mock
def test_onboard_identity_file_is_private_and_resumes(tmp_path: pathlib.Path):
    respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(201, json=ONBOARD_BODY))
    path = tmp_path / "identity.json"
    joined = AgentXClient.onboard("MyBot", base_url=BASE, identity_path=str(path))
    joined.close()
    if sys.platform != "win32":
        assert _mode(path) == 0o600
    resumed = AgentXClient("", base_url=BASE, identity_path=str(path))
    assert resumed.agent_did == DID
    assert resumed._identity_path == str(path)
    resumed.close()
