"""
Docs stay reachable, and the published schema matches what answers.

``GET /docs`` and ``GET /redoc`` used to be switched off when
``APP_ENV=production`` while ``GET /openapi.json`` stayed 200. They are the
framework's Swagger UI and ReDoc and are served in every environment.

Phase C routes that answer 404 while their flag is off (``GET /stats/economy``,
``GET /markets/bounties/showcase``, ``POST /wallets/faucet``) stay mounted —
404 is the off signal — but are left out of ``/openapi.json`` until the flag
is on. A parameter-free operation in the schema must not be an unconditional
404. Templated paths are not probed: an unknown id is a real 404.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import app, public_docs_urls
from src.services import economy_stats
from src.services.economy_stats import Counter, EconomyStats

PLATFORM_DIR = Path(__file__).resolve().parent.parent
client = TestClient(app, raise_server_exceptions=False)

_HTTP = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def test_docs_urls_do_not_depend_on_environment():
    assert public_docs_urls() == ("/docs", "/redoc")
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"


def test_docs_and_redoc_serve_the_schema_browsers():
    docs = client.get("/docs")
    redoc = client.get("/redoc")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert "/openapi.json" in docs.text
    assert redoc.status_code == 200
    assert "redoc" in redoc.text.lower()
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["openapi"].startswith("3.")


def test_production_serves_docs_and_hides_gated_phase_c_routes():
    """A fresh process with ``APP_ENV=production`` (the case that 404'd)."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("DISABLED_ROUTERS", "ALLOW_UNSAFE_ROUTERS")
    }
    env["APP_ENV"] = "production"
    env["CORS_ORIGINS"] = '["https://agentx.social"]'
    env["REDIS_URL"] = "memory://"
    code = (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "import src.main as m\n"
        "c = TestClient(m.app, raise_server_exceptions=False)\n"
        "docs, redoc = c.get('/docs'), c.get('/redoc')\n"
        "paths = c.get('/openapi.json').json()['paths']\n"
        "print('RESULT=' + json.dumps({\n"
        "  'production': m.settings.is_production,\n"
        "  'docs': docs.status_code,\n"
        "  'swagger': 'swagger-ui' in docs.text,\n"
        "  'redoc': redoc.status_code,\n"
        "  'economy': '/stats/economy' in paths,\n"
        "  'showcase': '/markets/bounties/showcase' in paths,\n"
        "  'faucet': '/wallets/faucet' in paths,\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PLATFORM_DIR, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("RESULT="))
    got = json.loads(line[len("RESULT="):])
    assert got == {
        "production": True,
        "docs": 200,
        "swagger": True,
        "redoc": 200,
        "economy": False,
        "showcase": False,
        "faucet": False,
    }


def test_economy_is_omitted_while_off_and_published_when_on(monkeypatch):
    assert "/stats/economy" not in app.openapi()["paths"]
    assert client.get("/stats/economy").status_code == 404

    monkeypatch.setattr(get_settings(), "economy_stats_enabled", "true")
    published = app.openapi()["paths"]["/stats/economy"]["get"]
    assert published["summary"].startswith("Economy counters")

    stats = EconomyStats(
        **{k: Counter(count=0, target=t) for k, t in economy_stats.TARGETS.items()},
        as_of=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    with patch.object(economy_stats, "get_stats", new=AsyncMock(return_value=stats)):
        assert client.get("/stats/economy").status_code == 200


def test_showcase_and_faucet_follow_their_flags(monkeypatch):
    paths = app.openapi()["paths"]
    assert "/markets/bounties/showcase" not in paths
    assert "/wallets/faucet" not in paths
    assert client.get("/markets/bounties/showcase").status_code == 404

    monkeypatch.setattr(get_settings(), "economy_showcase_enabled", "1")
    monkeypatch.setattr(get_settings(), "faucet_enabled", "true")
    paths = app.openapi()["paths"]
    assert "get" in paths["/markets/bounties/showcase"]
    assert "post" in paths["/wallets/faucet"]


def test_no_parameterless_openapi_path_is_an_unconditional_404():
    """Every published operation with no path parameter answers something
    other than 404 when called with an empty body and no token.

    No database: a route that needs one fails later (500). A flag that
    answers 404 before any read — the ``/stats/economy`` bug — fails here.
    """
    log = logging.getLogger("agentx.api")
    httpx_log = logging.getLogger("httpx")
    previous = log.level, httpx_log.level
    log.setLevel(logging.CRITICAL)
    httpx_log.setLevel(logging.CRITICAL)
    try:
        missing = []
        for path, ops in app.openapi()["paths"].items():
            if "{" in path:
                continue
            for method in ops:
                if method not in _HTTP:
                    continue
                status = client.request(method.upper(), path).status_code
                if status == 404:
                    missing.append(f"{method.upper()} {path}")
    finally:
        log.setLevel(previous[0])
        httpx_log.setLevel(previous[1])
    assert missing == []
