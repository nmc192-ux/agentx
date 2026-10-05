"""
agentx_client — deprecated alias for the AgentX Python SDK.

The SDK's PyPI name is ``agentx-py``. Replace::

    pip install agentx-client
    from agentx_client import AgentXClient

with::

    pip install agentx-py
    from agentx import AgentXClient

Everything here is re-exported from :mod:`agentx_sdk`, so existing code keeps
working while it migrates. Deprecation period: this import works for the whole
0.x series of agentx-py and is removed no earlier than agentx-py 1.0, with at
least 90 days' notice in the agentx-py CHANGELOG.
"""

import warnings

warnings.warn(
    "The 'agentx-client' package is deprecated and will receive no further "
    "updates. Install 'agentx-py' instead (pip install agentx-py) and import "
    "from 'agentx' (from agentx import AgentXClient). This 'agentx_client' "
    "import keeps working for the whole 0.x series of agentx-py and will be "
    "removed no earlier than agentx-py 1.0, with at least 90 days' notice in "
    "the agentx-py CHANGELOG.",
    DeprecationWarning,
    stacklevel=2,
)

from agentx_sdk import *  # noqa: E402,F401,F403
from agentx_sdk import __all__, __version__  # noqa: E402,F401
