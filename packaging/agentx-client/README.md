# agentx-client (deprecated)

**This package name is deprecated. Use [`agentx-py`](https://pypi.org/project/agentx-py/).**

```bash
pip uninstall agentx-client
pip install agentx-py
```

```python
from agentx import AgentXClient
```

Installing `agentx-client` now simply installs `agentx-py`. Code that imports
`agentx_sdk` keeps working unchanged. Code that imports `agentx_client` keeps
working too, but shows a `DeprecationWarning`; switch it to `from agentx import ...`.

`agentx-client` will receive no further releases.

## Deprecation period

- The final `agentx-client` release stays on PyPI permanently and keeps installing
  `agentx-py`, so old `pip install agentx-client` lines never break.
- The `agentx_client` import shim warns (`DeprecationWarning`) for the whole 0.x series of
  `agentx-py`.
- It is removed no earlier than `agentx-py` 1.0, and only after at least 90 days' notice in
  the `agentx-py` [CHANGELOG](https://github.com/nmc192-ux/agentx/blob/main/sdk/CHANGELOG.md).
