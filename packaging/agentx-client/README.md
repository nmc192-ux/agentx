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
