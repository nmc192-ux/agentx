#!/usr/bin/env python3
"""
Run scripts/remove_test_accounts.py against the app's own database (H25, Layer 1 S1-4).

The VPS ops tasks ``test-accounts-report`` and ``test-accounts-remove`` call this inside the
``migrate`` container. It only supplies the connection: host, port, user, database and TLS mode
come from the app settings (settings.env), the password from wherever the app reads it
(api.env or a secret file). They are handed to the reviewed script through libpq's PG*
environment variables and an empty ``postgresql://`` DSN, so the password is never on a
command line and never printed. Every other argument goes to the script unchanged, and the
script's own rules decide what may be removed.

  python scripts/vps_test_accounts.py show
  python scripts/vps_test_accounts.py remove
  python scripts/vps_test_accounts.py remove --apply --by "DrJ (VPS ops)" --did did:agentx:...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import remove_test_accounts  # noqa: E402


def pg_env(settings) -> dict[str, str]:
    """libpq variables for the app's database (asyncpg reads them for an empty DSN)."""
    mode = (settings.postgres_ssl_mode or "").lower() or "disable"
    return {
        "PGHOST": settings.postgres_host,
        "PGPORT": str(settings.postgres_port),
        "PGUSER": settings.postgres_user,
        "PGPASSWORD": settings.postgres_password,
        "PGDATABASE": settings.postgres_db,
        "PGSSLMODE": mode,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # The command must come first. The reviewed script takes --dsn only before the command, and
    # argparse accepts abbreviations there (--ds, --d), so an option in front of the command is
    # refused outright; after the command, the script's own parser rejects any --dsn.
    if not args or args[0] not in ("show", "remove"):
        print("vps_test_accounts: the first argument must be `show` or `remove`; the database "
              "comes from the app settings and no option may come before the command",
              file=sys.stderr)
        return 2
    if any(a == "--dsn" or a.startswith("--dsn=") for a in args):
        print("vps_test_accounts: the database comes from the app settings; do not pass --dsn",
              file=sys.stderr)
        return 2
    from src.config import get_settings
    os.environ.update(pg_env(get_settings()))
    sys.argv = ["remove_test_accounts.py", "--dsn", "postgresql://", *args]
    return remove_test_accounts.main()


if __name__ == "__main__":
    sys.exit(main())
