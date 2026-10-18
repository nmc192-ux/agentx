#!/usr/bin/env python3
"""Scan the public SDK export for internal details and secrets.

    python3 -I scripts/scan_public_sdk.py [EXPORT_DIR]     (default /tmp/agentx-sdk-export)

Prints one line per finding (``path:line: rule: text``) and exits 1 if there is any finding
that is not on the explained allow-list below. The secret rules are a fallback for when
gitleaks is not installed; run gitleaks as well when it is.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

INTERNAL = {
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "fly.dev": re.compile(r"fly\.dev|fly\.io|flyctl", re.I),
    "vps-host": re.compile(r"\bvps\b|hetzner|contabo|digitalocean|\bssh\s", re.I),
    "private-repo": re.compile(r"nmc192-ux/agentx(?!-sdk)\b|github\.com/[\w-]+/agentx(?![\w-])"),
    "platform-path": re.compile(r"\bplatform/|docs/(?:execution|strategy|sprints)|HUMAN_ACTIONS|ENGINE_LOG"),
    "internal-name": re.compile(r"\bDrJ\b|\bengine/phase|Mac mini", re.I),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "private-folder": re.compile(r"\b(?:runners|agentx-examples|packaging|orchestrator)/"),
    "link-out-of-package": re.compile(r"\]\((?:\.\./)+(?!sdk/|skills/|LICENSE\)|README\.md\))[^)]*\)"),
}
SECRET = {
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "pypi-token": re.compile(r"\bpypi-[A-Za-z0-9_-]{40,}"),
    "npm-token": re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"),
    "anthropic/openai-key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{30,}"),
    "slack-token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "db-url-with-password": re.compile(r"\b(?:postgres(?:ql)?|redis|mysql)://[^\s:/@]+:[^\s@/]+@"),
}

# (rule, path regex, text regex, reason): matches that are fine to publish.
ALLOWED: list[tuple[str, str, str, str]] = [
    ("email", r".", r"@(?:example\.(?:com|org)|agentx\.social)$", "example or public contact address"),
    ("fly.dev", r"^sdk/tests/test_default_base_url\.py$", r"^fly\.dev$",
     "the test forbids a hosting provider's address as the default; names no host of ours"),
]


def allowed_ipv4(text: str) -> bool:
    """Loopback, documentation (RFC 5737) and version-number-shaped strings only."""
    parts = [int(p) for p in text.split(".")]
    if any(p > 255 for p in parts):
        return True  # not an address (e.g. a version string)
    if parts[0] in (0, 127) or parts[:3] in ([192, 0, 2], [198, 51, 100], [203, 0, 113]):
        return True
    return False


def is_allowed(rule: str, rel: str, text: str) -> bool:
    if rule == "ipv4":
        return allowed_ipv4(text)
    return any(r == rule and re.search(pr, rel) and re.search(tr, text) for r, pr, tr, _ in ALLOWED)


def scan(root: Path) -> tuple[list[str], list[str]]:
    bad: list[str] = []
    ok: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            bad.append(f"{rel}: binary file in export")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for rules, kind in ((INTERNAL, "internal"), (SECRET, "secret")):
                for rule, rx in rules.items():
                    for m in rx.finditer(line):
                        entry = f"{rel}:{n}: {kind}/{rule}: {m.group(0)}"
                        (ok if kind == "internal" and is_allowed(rule, rel.as_posix(), m.group(0)) else bad).append(entry)
    return bad, ok


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/agentx-sdk-export")
    if not root.is_dir():
        print(f"no export at {root}; run scripts/export_public_sdk.sh first", file=sys.stderr)
        return 2
    bad, ok = scan(root)
    for e in ok:
        print(f"allowed  {e}")
    for e in bad:
        print(f"FINDING  {e}")
    print(f"{len(bad)} finding(s), {len(ok)} allowed match(es)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
