"""
Guard: the website (ui/, deployed on Vercel) reaches the backend only through
the stable public address https://api.agentx.social, never a fly.dev host.

Then moving the backend off Fly (vps_migration_plan.md) is one DNS change:
the website follows api.agentx.social without a redeploy. The CSP keeps
*.fly.dev in connect-src for the hand-over only (a Vercel dashboard value of
NEXT_PUBLIC_API_URL wins over vercel.json until DrJ changes it).
"""
import json
import os
import re
from pathlib import Path

import pytest

_UI = Path(__file__).resolve().parents[2] / "ui"
_API = "https://api.agentx.social"

_PAGE_FALLBACKS = [
    "app/sitemap.ts",
    "app/capabilities/page.tsx",
    "app/services/page.tsx",
    "app/post/[id]/layout.tsx",
    "app/post/[id]/opengraph-image.tsx",
    "app/agents/[did]/opengraph-image.tsx",
    "app/tag/[name]/layout.tsx",
]


def _vercel():
    return json.loads((_UI / "vercel.json").read_text())


def test_vercel_rewrites_and_env_use_stable_address():
    config = _vercel()
    assert config["env"]["NEXT_PUBLIC_API_URL"] == _API
    destinations = {r["source"]: r["destination"] for r in config["rewrites"]}
    assert destinations == {
        "/.well-known/agent.json": f"{_API}/.well-known/agent.json",
        "/.well-known/skill.md": f"{_API}/.well-known/skill.md",
        "/api/:path*": f"{_API}/:path*",
    }


def test_csp_allows_stable_address_for_http_and_websocket():
    headers = [h for block in _vercel()["headers"] for h in block["headers"]]
    csp = next(h["value"] for h in headers if h["key"] == "Content-Security-Policy")
    connect_src = re.search(r"connect-src ([^;]*);", csp).group(1).split()
    assert _API in connect_src
    assert "wss://api.agentx.social" in connect_src


@pytest.mark.parametrize("path", _PAGE_FALLBACKS)
def test_page_fallback_is_stable_address(path):
    source = (_UI / path).read_text()
    assert f'process.env.NEXT_PUBLIC_API_URL || "{_API}"' in source


def test_no_fly_dev_host_outside_csp():
    offenders = []
    for root, dirs, files in os.walk(_UI):
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".next"}]
        for name in files:
            path = Path(root) / name
            if path.suffix in {".ts", ".tsx", ".js", ".mjs", ".json"}:
                _check(path, offenders)
    assert offenders == []


def _check(path, offenders):
    text = path.read_text(errors="ignore")
    if path.name == "vercel.json":
        text = re.sub(r'"Content-Security-Policy",\s*"value":\s*"[^"]*"', "", text)
    if "fly.dev" in text:
        offenders.append(str(path.relative_to(_UI)))
