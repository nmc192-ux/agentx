import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """No test sees the developer's real credentials or base URL."""
    for name in ("AGENTX_TOKEN", "AGENTX_REFRESH_TOKEN", "AGENTX_AGENT_DID", "AGENTX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTX_CREDENTIALS_FILE", str(tmp_path / "agentx" / "credentials.json"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
