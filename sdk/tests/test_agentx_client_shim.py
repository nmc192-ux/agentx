"""
The deprecated `agentx-client` package (packaging/agentx-client) must stay a
pure shim: it depends on agentx-py, warns on import, re-exports agentx_sdk,
and ships no package that agentx-py also ships.
"""

import importlib.util
import tomllib
import warnings
from pathlib import Path

import agentx_sdk

REPO = Path(__file__).resolve().parents[2]
SHIM = REPO / "packaging" / "agentx-client"
SDK = REPO / "sdk"


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def _load_shim():
    spec = importlib.util.spec_from_file_location(
        "agentx_client_under_test", SHIM / "agentx_client" / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_warns_deprecated():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _load_shim()
    messages = [str(w.message) for w in caught if w.category is DeprecationWarning]
    assert messages, "importing agentx_client must emit a DeprecationWarning"
    assert "agentx-py" in messages[0]


def test_reexports_the_real_sdk():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        shim = _load_shim()
    assert shim.AgentXClient is agentx_sdk.AgentXClient
    assert shim.__version__ == agentx_sdk.__version__
    for name in agentx_sdk.__all__:
        assert getattr(shim, name) is getattr(agentx_sdk, name)


def test_depends_on_agentx_py_and_ships_only_the_alias():
    shim = _toml(SHIM / "pyproject.toml")
    sdk = _toml(SDK / "pyproject.toml")
    assert shim["project"]["name"] == "agentx-client"
    assert sdk["project"]["name"] == "agentx-py"
    assert any(d.startswith("agentx-py") for d in shim["project"]["dependencies"])
    shim_pkgs = set(shim["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    sdk_pkgs = set(sdk["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    assert shim_pkgs == {"agentx_client"}
    assert not shim_pkgs & sdk_pkgs


def test_shim_version_is_above_last_published_agentx_client():
    # agentx-client 0.2.0 is on PyPI; pip only moves people to the shim if it is newer.
    version = tuple(int(p) for p in _toml(SHIM / "pyproject.toml")["project"]["version"].split("."))
    assert version > (0, 2, 0)
