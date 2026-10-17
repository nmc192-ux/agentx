"""
Tests: deploy/vps/db_move.sh (DB-1) — moving the database from Neon to the VPS Postgres.

Rehearsed natively against local Postgres (PG_RUN=native): a scratch "Neon" database built with
the real migration chain and some rows (incl. a pgvector column and sequences), an empty scratch
"VPS" database. Pins what the runbook relies on:
  1. dump + restore gives a copy whose every table has the same row count and the same alembic
     version (verify says OK), with the pgvector column and the rows intact;
  2. verify fails when one row differs;
  3. restore refuses a database that already has tables, and a broken dump leaves nothing behind;
  4. backup keeps only the newest KEEP files and never deletes neon-*.dump;
  5. the Neon password never appears on a command line (it goes in on stdin);
  6. restore-test (LR-2) loads the newest nightly backup into a throwaway database, compares it
     with the live one and drops it; a missing, empty, corrupt or stale backup, a backup that
     lost most of its rows, and a target named like the live database all fail with an ALERT.
"""
import getpass
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLATFORM = REPO / "platform"
SCRIPT = REPO / "deploy" / "vps" / "db_move.sh"
SRC_DB = "agentx_smoke_dbmove_src"
DST_DB = "agentx_smoke_dbmove_dst"
PG_USER = getpass.getuser()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pg_dump") is None, reason="Postgres client tools not installed"),
]


def _pg(*args: str, db: str = "postgres") -> str:
    out = subprocess.run(
        ["psql", "-X", "-At", "-h", "localhost", "-U", PG_USER, "-d", db, "-v", "ON_ERROR_STOP=1", *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _fresh(db: str) -> None:
    _pg("-c", f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
    _pg("-c", f"CREATE DATABASE {db}")


@pytest.fixture(scope="module")
def source_db():
    """Scratch 'Neon': the real migration chain plus a few rows."""
    spec = importlib.util.spec_from_file_location("smoke_routers", PLATFORM / "scripts" / "smoke_routers.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_")},
        "APP_ENV": "development", "POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5432",
        "POSTGRES_USER": PG_USER, "POSTGRES_DB": SRC_DB, "POSTGRES_PASSWORD": "local-trust",
        "POSTGRES_SSL_MODE": "disable", "REDIS_URL": "memory://", "JWT_SECRET": "x" * 40,
    }
    smoke.build_database(SRC_DB, env)
    _pg("-c", """
        INSERT INTO agents (agent_did, display_name)
        SELECT 'did:agentx:dbmove-' || lpad(g::text, 3, '0'), 'mover ' || g FROM generate_series(1, 25) g
    """, db=SRC_DB)
    yield SRC_DB
    _pg("-c", f"DROP DATABASE IF EXISTS {SRC_DB} WITH (FORCE)")


@pytest.fixture
def workdir(tmp_path):
    (tmp_path / "settings.env").write_text(
        "POSTGRES_HOST=ep-example-pooler.c-6.us-east-1.aws.neon.tech\nPOSTGRES_PORT=5432\n"
        "POSTGRES_USER=neondb_owner\nPOSTGRES_DB=neondb\n"
    )
    secrets = tmp_path / "api.env"
    secrets.write_text("JWT_SECRET=unused\nPOSTGRES_PASSWORD=neon-pw-sentinel-123\n")
    _fresh(DST_DB)
    yield tmp_path
    _pg("-c", f"DROP DATABASE IF EXISTS {DST_DB} WITH (FORCE)")


def run(workdir: Path, *args: str, **extra) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "AGENTX_DIR": str(workdir),
        "BACKUP_DIR": str(workdir / "backups"),
        "AGENTX_SECRETS_FILE": str(workdir / "api.env"),
        "PG_RUN": "native",
        "SRC_HOST": "localhost", "SRC_USER": PG_USER, "SRC_DB": SRC_DB, "SRC_SSLMODE": "disable",
        # The VPS side, as the db container's environment would give it.
        "PGHOST": "localhost", "POSTGRES_USER": PG_USER, "POSTGRES_DB": DST_DB,
        **extra,
    }
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=300)


def _dump(workdir: Path) -> Path:
    result = run(workdir, "dump")
    assert result.returncode == 0, result.stderr
    dumps = sorted((workdir / "backups").glob("neon-*.dump"))
    assert len(dumps) == 1 and not list((workdir / "backups").glob("*.part"))
    assert oct(dumps[0].stat().st_mode & 0o777) == "0o600"
    return dumps[0]


def test_check_reports_versions_and_empty_target(source_db, workdir):
    result = run(workdir, "check")
    assert result.returncode == 0, result.stderr
    assert "must be 0 before restore" in result.stdout and "tables: 0" in result.stdout
    assert "extensions: all available" in result.stdout
    assert result.stdout.strip().endswith("OK")


def test_check_fails_on_extension_missing_on_vps(source_db, workdir, tmp_path):
    """A Neon-only extension would break the restore halfway; check must say so first."""
    shim = tmp_path / "bin"
    shim.mkdir()
    real = shutil.which("psql")
    # The VPS side answers "not available" for every extension.
    (shim / "psql").write_text(
        f'#!/bin/sh\ncase "$*" in *pg_available_extensions*) echo 0;; *) exec {real} "$@";; esac\n'
    )
    (shim / "psql").chmod(0o755)
    result = run(workdir, "check", PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode == 1
    assert "extensions the VPS server does not have" in result.stderr and "vector" in result.stderr


def test_dump_restore_verify_round_trip(source_db, workdir):
    dump = _dump(workdir)
    restored = run(workdir, "restore", str(dump))
    assert restored.returncode == 0, restored.stdout + restored.stderr
    verified = run(workdir, "verify")
    assert verified.returncode == 0, verified.stderr
    assert "OK:" in verified.stdout and "agents" in verified.stdout
    # Same migration head, same rows, sequences carried over, pgvector column present.
    assert _pg("-c", "SELECT version_num FROM alembic_version", db=DST_DB) == \
        _pg("-c", "SELECT version_num FROM alembic_version", db=SRC_DB)
    assert _pg("-c", "SELECT count(*) FROM agents WHERE agent_did LIKE 'did:agentx:dbmove-%'", db=DST_DB) == "25"
    assert _pg("-c", "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                     "WHERE attrelid = 'posts'::regclass AND attname = 'embedding'", db=DST_DB) == "vector(1536)"
    # Restoring again into the now-full database is refused, and changes nothing.
    again = run(workdir, "restore", str(dump))
    assert again.returncode == 1 and "refusing" in again.stderr
    assert run(workdir, "verify").returncode == 0


def test_verify_fails_on_one_row_difference(source_db, workdir):
    assert run(workdir, "restore", str(_dump(workdir))).returncode == 0
    _pg("-c", "DELETE FROM agents WHERE agent_did = 'did:agentx:dbmove-007'", db=DST_DB)
    result = run(workdir, "verify")
    assert result.returncode == 1
    assert "DIFFERENT" in result.stderr and "agents|" in result.stderr


def test_broken_dump_leaves_target_empty(source_db, workdir):
    dump = _dump(workdir)
    data = dump.read_bytes()
    broken = workdir / "broken.dump"
    broken.write_bytes(data[: len(data) // 2])
    result = run(workdir, "restore", str(broken))
    assert result.returncode == 1
    assert _pg("-c", "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'", db=DST_DB) == "0"


def test_backup_rotates_and_keeps_neon_dumps(source_db, workdir):
    assert run(workdir, "restore", str(_dump(workdir))).returncode == 0
    backups = workdir / "backups"
    for i in range(4):  # older nightly files
        old = backups / f"agentx-2026010{i}-000000.dump"
        old.write_bytes(b"old")
        os.utime(old, (1_700_000_000 + i, 1_700_000_000 + i))
    result = run(workdir, "backup", KEEP="3")
    assert result.returncode == 0, result.stderr
    kept = sorted(p.name for p in backups.glob("agentx-*.dump"))
    assert len(kept) == 3
    assert "agentx-20260103-000000.dump" in kept and "agentx-20260102-000000.dump" in kept
    assert len(list(backups.glob("neon-*.dump"))) == 1
    newest = max(backups.glob("agentx-*.dump"), key=lambda p: p.stat().st_mtime)
    listing = subprocess.run(["pg_restore", "--list", str(newest)], capture_output=True, text=True)
    assert listing.returncode == 0 and "TABLE DATA public agents" in listing.stdout


def test_neon_password_only_on_stdin(source_db, workdir, tmp_path):
    """Wrap psql/pg_dump: record their argv and environment; the password must not be in argv."""
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "argv.log"
    for tool in ("psql", "pg_dump", "pg_restore"):
        real = shutil.which(tool)
        (shim / tool).write_text(
            f'#!/bin/sh\necho "$0 $*" >> {log}\necho "pw=${{PGPASSWORD:-}}" >> {log}\nexec {real} "$@"\n'
        )
        (shim / tool).chmod(0o755)
    path = f"{shim}{os.pathsep}{os.environ['PATH']}"
    assert run(workdir, "check", PATH=path).returncode == 0
    assert run(workdir, "dump", PATH=path).returncode == 0
    text = log.read_text()
    argv_lines = [line for line in text.splitlines() if not line.startswith("pw=")]
    assert argv_lines and not any("neon-pw-sentinel-123" in line for line in argv_lines)
    # ...but it did reach the tools that talk to the "Neon" side.
    assert "pw=neon-pw-sentinel-123" in text


def test_verify_full_is_the_default_and_fails_closed_without_a_verified_server(source_db, workdir, tmp_path):
    """SR-1: with no SRC_SSLMODE given, the Neon-side tools get verify-full and a
    root cert; a server that cannot be verified (local Postgres, no TLS) makes
    `check` stop before anything is read. The VPS-side tools get no SSL settings."""
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "env.log"
    real = shutil.which("psql")
    (shim / "psql").write_text(
        f'#!/bin/sh\necho "host=${{PGHOST:-}} ssl=${{PGSSLMODE:-}} root=${{PGSSLROOTCERT:-}}" >> {log}\nexec {real} "$@"\n'
    )
    (shim / "psql").chmod(0o755)
    env = {k: v for k, v in os.environ.items()}
    result = run(workdir, "check", PATH=f"{shim}{os.pathsep}{env['PATH']}",
                 SRC_SSLMODE="", SRC_SSLROOTCERT=str(tmp_path / "ca.crt"))
    assert result.returncode != 0
    assert "SSL" in result.stderr or "ssl" in result.stderr or "root certificate" in result.stderr
    lines = log.read_text().splitlines()
    assert lines and lines[0] == f"host=localhost ssl=verify-full root={tmp_path / 'ca.crt'}"
    assert not any("ssl=verify-full" in line and "host=" + "localhost ssl=verify" not in line for line in lines[1:])
    assert not (workdir / "backups").exists() or not list((workdir / "backups").glob("*.dump"))


def test_root_cert_only_named_when_the_mode_verifies(source_db, workdir, tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "env.log"
    real = shutil.which("psql")
    (shim / "psql").write_text(
        f'#!/bin/sh\necho "ssl=${{PGSSLMODE:-}} root=${{PGSSLROOTCERT:-unset}}" >> {log}\nexec {real} "$@"\n'
    )
    (shim / "psql").chmod(0o755)
    result = run(workdir, "check", PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")   # SRC_SSLMODE=disable
    assert result.returncode == 0, result.stderr
    assert "sslmode disable" in result.stdout
    assert "root=unset" in log.read_text() and "ssl=verify" not in log.read_text()


def test_refuses_to_run_without_a_source_host(workdir):
    # EL-3: settings.env names the VPS `db`; it is never taken as the Neon side.
    (workdir / "settings.env").write_text("POSTGRES_HOST=db\nPOSTGRES_PORT=5432\nPOSTGRES_USER=u\nPOSTGRES_DB=d\n")
    result = run(workdir, "check", SRC_HOST="")
    assert result.returncode == 1
    assert "no SRC_HOST" in result.stderr


def test_usage_and_missing_file(workdir):
    assert run(workdir).returncode == 2
    assert run(workdir, "restore", str(workdir / "nope.dump")).returncode == 2


# ── restore-test (LR-2) ─────────────────────────────────────────────────────────────

RT_DB = "agentx_restore_test"


def _db_exists(name: str) -> bool:
    return _pg("-c", f"SELECT count(*) FROM pg_database WHERE datname = '{name}'") == "1"


@pytest.fixture
def live_with_backup(source_db, workdir):
    """The 'VPS' database filled from the source, plus one fresh nightly backup of it."""
    assert run(workdir, "restore", str(_dump(workdir))).returncode == 0
    result = run(workdir, "backup")
    assert result.returncode == 0, result.stderr
    yield workdir
    _pg("-c", f"DROP DATABASE IF EXISTS {RT_DB} WITH (FORCE)")


def _newest_backup(workdir: Path) -> Path:
    return max((workdir / "backups").glob("agentx-*.dump"), key=lambda p: p.stat().st_mtime)


def _status(workdir: Path) -> str:
    return (workdir / "backups" / "restore-test.status").read_text()


def _assert_alert(result: subprocess.CompletedProcess, words: str) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ALERT: backup restore-test failed" in result.stderr and words in result.stderr, result.stderr
    assert not _db_exists(RT_DB)


def test_restore_test_passes_and_drops_the_throwaway(live_with_backup):
    workdir = live_with_backup
    live_before = _pg("-c", "SELECT count(*) FROM agents", db=DST_DB)
    result = run(workdir, "restore-test", SRC_HOST="")   # needs no Neon settings
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: restore-test agentx-" in result.stdout and "throwaway database dropped" in result.stdout
    assert "agents" in result.stdout
    assert not _db_exists(RT_DB)
    assert _status(workdir).startswith("ok ")
    # The live database was only read.
    assert _pg("-c", "SELECT count(*) FROM agents", db=DST_DB) == live_before


def test_restore_test_tolerates_a_day_of_new_rows(live_with_backup):
    _pg("-c", "INSERT INTO agents (agent_did, display_name) VALUES ('did:agentx:after-backup-001', 'late')", db=DST_DB)
    result = run(live_with_backup, "restore-test")
    assert result.returncode == 0, result.stderr


def test_restore_test_fails_on_a_backup_that_lost_most_rows(live_with_backup):
    _pg("-c", """
        INSERT INTO agents (agent_did, display_name)
        SELECT 'did:agentx:bulk' || g || '-001', 'bulk ' || g FROM generate_series(1, 2000) g
    """, db=DST_DB)
    _assert_alert(run(live_with_backup, "restore-test"), "rows")
    assert _status(live_with_backup).startswith("fail ")


def test_restore_test_fails_on_a_truncated_backup(live_with_backup):
    newest = _newest_backup(live_with_backup)
    data = newest.read_bytes()
    newest.write_bytes(data[: len(data) // 2])
    _assert_alert(run(live_with_backup, "restore-test"), "")
    assert _status(live_with_backup).startswith("fail ")


def test_restore_test_fails_on_garbage_and_empty_files(live_with_backup):
    newest = _newest_backup(live_with_backup)
    newest.write_bytes(b"not a dump at all")
    _assert_alert(run(live_with_backup, "restore-test"), "not a readable dump")
    newest.write_bytes(b"")
    _assert_alert(run(live_with_backup, "restore-test"), "is empty")


def test_restore_test_fails_on_a_stale_backup(live_with_backup):
    newest = _newest_backup(live_with_backup)
    old = newest.stat().st_mtime - 27 * 3600
    os.utime(newest, (old, old))
    _assert_alert(run(live_with_backup, "restore-test"), "older than 26 h")
    assert run(live_with_backup, "restore-test", MAX_BACKUP_AGE_H="30").returncode == 0


def test_restore_test_fails_without_backups(workdir):
    _assert_alert(run(workdir, "restore-test"), "no backup folder")
    (workdir / "backups").mkdir(exist_ok=True)
    (workdir / "backups" / "neon-20261101-000000.dump").write_bytes(b"x")   # not a nightly
    _assert_alert(run(workdir, "restore-test"), "no agentx-*.dump")


def test_restore_test_never_targets_the_live_database(live_with_backup):
    workdir = live_with_backup
    live_tables = _pg("-c", "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'", db=DST_DB)
    for target in (DST_DB, "postgres", "agentx_restore_test; DROP DATABASE x", "Agentx_Restore_Test"):
        result = run(workdir, "restore-test", RESTORE_TEST_DB=target)
        assert result.returncode == 1 and "refusing" in result.stderr, (target, result.stderr)
    # The live database's name itself, even when it looks like a restore-test name.
    result = run(workdir, "restore-test", RESTORE_TEST_DB="agentx_restore_test_live", POSTGRES_DB="agentx_restore_test_live")
    assert result.returncode == 1 and "is the live database" in result.stderr
    assert _pg("-c", "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'", db=DST_DB) == live_tables


def test_restore_test_fails_on_another_migration_version(live_with_backup):
    _pg("-c", "UPDATE alembic_version SET version_num = 'zzz_newer'", db=DST_DB)
    _assert_alert(run(live_with_backup, "restore-test"), "migration version")


# ── LR-6a: sprint-close review of restore-test (adversarial) ─────────────────────────


def _no_tmp_status(workdir: Path) -> None:
    assert not (workdir / "backups" / "restore-test.status.tmp").exists()


def test_restore_test_refuses_when_the_data_disk_is_short(live_with_backup):
    """The throwaway copy shares the live cluster's disk: filling it would stop the live database,
    so a dump that would not fit (factor pushed absurdly high) is refused before anything is created."""
    workdir = live_with_backup
    if _pg("-c", "SHOW data_directory") == "":
        pytest.skip("cannot read data_directory here")
    live_before = _pg("-c", "SELECT count(*) FROM agents", db=DST_DB)
    result = run(workdir, "restore-test", RESTORE_DISK_FACTOR="1000000000")
    _assert_alert(result, "not enough free disk")
    assert "KB free on the data disk" in result.stderr and "RESTORE_DISK_FACTOR" in result.stderr
    assert _status(workdir).startswith("fail ") and "not enough free disk" in _status(workdir)
    _no_tmp_status(workdir)
    assert _pg("-c", "SELECT count(*) FROM agents", db=DST_DB) == live_before
    # The default factor lets a small dump through, and the guard stands aside (with a note)
    # when the free space cannot be read instead of blocking the test.
    assert run(workdir, "restore-test").returncode == 0
    fake = workdir / "bin"
    fake.mkdir()
    (fake / "df").write_text("#!/bin/sh\nexit 1\n")
    (fake / "df").chmod(0o755)
    result = run(workdir, "restore-test", PATH=f"{fake}:{os.environ['PATH']}")
    assert result.returncode == 0, result.stderr
    assert "could not read the free space" in result.stderr


def test_restore_test_alert_names_the_pg_restore_error(live_with_backup):
    """A dump whose data blocks are damaged still passes `pg_restore --list` (the table of contents
    is at the front), so the real restore is what fails; the alert must carry pg_restore's own
    words, not just 'an error'."""
    workdir = live_with_backup
    newest = _newest_backup(workdir)
    data = bytearray(newest.read_bytes())
    data[-4096:] = b"\0" * 4096
    newest.write_bytes(bytes(data))
    assert subprocess.run(["pg_restore", "--list", str(newest)], capture_output=True).returncode == 0
    result = run(workdir, "restore-test")
    _assert_alert(result, "pg_restore of ")
    assert "stopped: pg_restore: error:" in result.stderr, result.stderr
    assert "stopped: pg_restore: error:" in _status(workdir)
    _no_tmp_status(workdir)


def test_restore_test_status_is_written_whole(live_with_backup):
    """ok and fail results both land by rename, so the watchdog never reads a half-written line."""
    workdir = live_with_backup
    assert run(workdir, "restore-test").returncode == 0
    assert _status(workdir).startswith("ok ") and _status(workdir).endswith("rows\n")
    _no_tmp_status(workdir)
    _assert_alert(run(workdir, "restore-test", RESTORE_TEST_DB="postgres"), "refusing")
    assert _status(workdir).startswith("fail ") and _status(workdir).count("\n") == 1
    _no_tmp_status(workdir)


def test_restore_test_ignores_part_files_and_neon_dumps(live_with_backup):
    """A dump still being written (or left behind by a crash) and the one-off Neon copies are never
    taken for 'the newest nightly backup', however new they are."""
    workdir = live_with_backup
    backups = workdir / "backups"
    (backups / "agentx-29990101-000000.dump.part").write_bytes(b"half written")
    (backups / "neon-29990101-000000.dump").write_bytes(b"not a nightly")
    result = run(workdir, "restore-test")
    assert result.returncode == 0, result.stderr
    assert "agentx-29990101" not in result.stdout and "neon-" not in result.stdout


def test_backup_sweeps_stale_part_files_only(live_with_backup):
    """A .part older than a day is debris from a dump that died; a fresh one may still be in flight."""
    workdir = live_with_backup
    backups = workdir / "backups"
    stale = backups / "agentx-20200101-000000.dump.part"
    fresh = backups / "agentx-29990101-000000.dump.part"
    stale.write_bytes(b"x" * 10)
    fresh.write_bytes(b"x" * 10)
    old = stale.stat().st_mtime - 2 * 24 * 3600
    os.utime(stale, (old, old))
    before = len(list(backups.glob("agentx-*.dump")))
    time.sleep(1.1)   # backup names carry the second; the fixture's backup may share this one
    result = run(workdir, "backup")
    assert result.returncode == 0, result.stderr
    assert not stale.exists() and fresh.exists()
    assert len(list(backups.glob("agentx-*.dump"))) == before + 1
    fresh.unlink()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "--db", "-v"]))
