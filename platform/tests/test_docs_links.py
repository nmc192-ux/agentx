"""Relative links in the front-door docs must resolve to real files."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = [
    "README.md",
    "sdk/README.md",
    "sdk/ts/README.md",
    "platform/docs/quickstart.md",
    "agentx-examples/README.md",
    "agentx-examples/ts/README.md",
]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)


def _targets(text: str):
    text = FENCE.sub("", text)
    for m in LINK.finditer(text):
        t = m.group(1)
        if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("#"):
            continue
        yield t.split("#", 1)[0].split("?", 1)[0]


@pytest.mark.parametrize("doc", DOCS)
def test_relative_links_resolve(doc):
    path = REPO / doc
    assert path.is_file(), doc
    missing = [
        t for t in _targets(path.read_text(encoding="utf-8"))
        if t and not (path.parent / t).resolve().exists()
    ]
    assert not missing, f"{doc}: broken links {missing}"
