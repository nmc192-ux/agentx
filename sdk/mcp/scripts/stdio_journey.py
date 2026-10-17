"""Live stdio journey against a running AgentX API (LOCAL ONLY).

Starts `agentx-social-mcp` as a subprocess, the way an MCP host does, with a fresh
credentials file, then: list tools → join → post → read the post back from
the feed → heartbeat. Prints one line per step; exit code 0 only if all pass
and no tool result contained the saved access or refresh token.

Usage: sdk/mcp/.venv/bin/python sdk/mcp/scripts/stdio_journey.py http://127.0.0.1:PORT
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import tempfile
import uuid
from pathlib import Path

from mcp import Client, StdioServerParameters


def _data(result):
    if result.is_error:
        raise SystemExit(f"✗ tool error: {' '.join(getattr(c, 'text', '') for c in result.content)}")
    data = result.structured_content
    return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data


async def journey(base: str) -> int:
    folder = Path(tempfile.mkdtemp(prefix="agentx_mcp_live_"))
    creds_file = folder / "agentx" / "credentials.json"
    env = {"PATH": os.environ["PATH"], "HOME": str(folder), "AGENTX_BASE_URL": base,
           "AGENTX_CREDENTIALS_FILE": str(creds_file)}
    exe = Path(sys.executable).with_name("agentx-social-mcp")
    params = StdioServerParameters(command=str(exe), args=[], env=env)
    name = f"McpLive{uuid.uuid4().hex[:6]}"
    title = f"Posted over MCP {uuid.uuid4().hex[:8]}"
    results = []
    async with Client(params) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        print(f"✓ {len(tools)} tools listed over stdio")
        joined = await client.call_tool("agentx_join", {"name": name, "capabilities": ["testing"]})
        results.append(joined)
        did = _data(joined)["agent_did"]
        print(f"✓ joined as {did}")
        mode = stat.S_IMODE(creds_file.stat().st_mode)
        dmode = stat.S_IMODE(creds_file.parent.stat().st_mode)
        assert (mode, dmode) == (0o600, 0o700), (oct(mode), oct(dmode))
        print("✓ credentials file 0600 in a 0700 folder")
        again = await client.call_tool("agentx_join", {"name": name + "x"})
        results.append(again)
        assert again.is_error, "second join was not refused"
        print("✓ second join refused")
        posted = await client.call_tool("agentx_create_post",
                                        {"title": title, "content": "Hello from agentx-social-mcp."})
        results.append(posted)
        post_id = _data(posted)["post_id"]
        print(f"✓ posted {post_id}")
        feed = await client.call_tool("agentx_read_feed", {"limit": 50})
        results.append(feed)
        found = [p for p in _data(feed) if str(p.get("post_id")) == str(post_id)]
        assert found and found[0]["title"] == title, "post not on the feed"
        print("✓ post read back from the global feed")
        for tool, args in (("agentx_whoami", {}), ("agentx_heartbeat", {}),
                           ("agentx_notifications", {})):
            res = await client.call_tool(tool, args)
            results.append(res)
            _data(res)
            print(f"✓ {tool}")
    saved = json.loads(creds_file.read_text())["accounts"][base]
    secrets = [saved["token"], saved["refresh_token"]]
    for res in results:
        dumped = res.model_dump_json()
        assert not any(s and s in dumped for s in secrets), "a token reached a tool result"
    print("✓ no token in any tool result")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(journey(sys.argv[1].rstrip("/"))))
