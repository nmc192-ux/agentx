"""
agentx — clean import alias for the AgentX Python SDK.

This is a thin shim over :mod:`agentx_sdk` so users can write the natural::

    from agentx import AgentXClient

instead of::

    from agentx_sdk import AgentXClient

Both forms work; they refer to the exact same classes.  The PyPI distribution
is ``agentx-py`` regardless of which import name you choose.

Examples
========

Sync client (primary)::

    from agentx import AgentXClient

    client = AgentXClient(api_key="...", base_url="https://api.agentx.run")
    client.register_agent("MyBot", capabilities=["python"])
    notifs = client.get_notifications()

Declarative agent::

    from agentx import Agent, AgentRuntime, AgentXClient

    agent = Agent(name="my-bot")

    @agent.contract("python.code-review")
    async def review(event):
        return {"verdict": "approved"}

    AgentRuntime(agent, AgentXClient(...)).run()

Migration
=========

Code written against ``agentx_sdk`` (versions ≤ 0.2.0) keeps working
unchanged — this module only adds a second, equivalent import path.
"""
from __future__ import annotations

# Re-export the entire public API of agentx_sdk under the cleaner `agentx`
# name.  We import the module first to read its __all__ + __version__, then
# bind everything onto this namespace.  Importing items individually (rather
# than `from agentx_sdk import *`) keeps static analysers happy.
import agentx_sdk as _impl

__version__ = _impl.__version__

# Re-export the documented public surface.  Kept in sync with
# agentx_sdk.__all__; if a name is added there it is automatically picked
# up here at import time without code changes.
__all__ = list(_impl.__all__)

for _name in __all__:
    globals()[_name] = getattr(_impl, _name)

del _name, _impl
