#!/usr/bin/env bash
# Copy the AgentX database from Neon to the VPS Postgres, check the copy, and take nightly
# backups (DB-1). Runbook: platform/docs/execution/db_move_runbook.md. Run on the VPS as `deploy`:
#
#   cd /opt/agentx && bash db_move.sh check            # versions, target empty?, disk (changes nothing)
#   cd /opt/agentx && bash db_move.sh dump             # Neon -> /var/backups/agentx/neon-<time>.dump
#   cd /opt/agentx && bash db_move.sh restore <file>   # into the EMPTY VPS database, all or nothing
#   cd /opt/agentx && bash db_move.sh verify           # exact row counts, Neon vs VPS, every table
#   cd /opt/agentx && bash db_move.sh backup           # VPS -> /var/backups/agentx/agentx-<time>.dump
#
# Every Postgres tool runs inside the `db` container (pg17 tools, so they can read a Neon server of
# version 17 or older). Neon is only ever read: pg_dump and SELECT count(*). The Neon password is
# read from api.env and handed to the tool on stdin, never on a command line or the screen. The
# VPS database is reached over the container's local socket (trusted by the postgres image).
#
# Local rehearsal (tests/infrastructure/test_db_move.py): PG_RUN=native runs the same commands on
# this machine instead of in the container; SRC_* point the "Neon" side at a scratch database.
set -euo pipefail

cd "${AGENTX_DIR:-/opt/agentx}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/agentx}"
KEEP="${KEEP:-14}"
SECRETS="${AGENTX_SECRETS_FILE:-/etc/agentx/api.env}"

env_value() {  # env_value FILE NAME -> last value of NAME in FILE, quotes removed
  local v
  v="$(sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -n 1)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

# The Neon side: settings.env as on Fly, but the direct endpoint, not the "-pooler" one
# (Neon's pooler is PgBouncer in transaction mode; pg_dump wants a plain session).
SRC_HOST="${SRC_HOST:-$(env_value settings.env POSTGRES_HOST | sed 's/-pooler\././')}"
SRC_PORT="${SRC_PORT:-$(env_value settings.env POSTGRES_PORT)}"
SRC_USER="${SRC_USER:-$(env_value settings.env POSTGRES_USER)}"
SRC_DB="${SRC_DB:-$(env_value settings.env POSTGRES_DB)}"
SRC_SSLMODE="${SRC_SSLMODE:-require}"

pg() {  # run a command where the Postgres tools are
  if [[ "${PG_RUN:-container}" == native ]]; then
    "$@"
  else
    docker compose --env-file compose.env --profile db exec -T db "$@"
  fi
}

src_password() {
  local p
  p="$(env_value "$SECRETS" POSTGRES_PASSWORD)"
  [[ -n "$p" ]] || { echo "no POSTGRES_PASSWORD in $SECRETS" >&2; return 1; }
  printf '%s\n' "$p"
}

# src TOOL ARGS... : run a libpq tool against Neon; password on stdin, stdout passed through.
src() {
  src_password | pg env PGHOST="$SRC_HOST" PGPORT="$SRC_PORT" PGUSER="$SRC_USER" \
    PGDATABASE="$SRC_DB" PGSSLMODE="$SRC_SSLMODE" PGCONNECT_TIMEOUT=20 \
    sh -c 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@" </dev/null' sh "$@"
}

# dst TOOL ARGS... : run a libpq tool against the VPS database (local socket in the container).
# stdin is passed through (restore reads the dump from it).
dst() {
  pg sh -c 'export PGUSER="$POSTGRES_USER" PGDATABASE="$POSTGRES_DB"; exec "$@"' sh "$@"
}

COUNT_SQL_GEN="SELECT coalesce(string_agg(format('SELECT %L AS t, count(*) AS n FROM public.%I', table_name, table_name), ' UNION ALL ' ORDER BY table_name), 'SELECT NULL, NULL WHERE false') FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"

counts() {  # counts src|dst -> "table|rows" lines, sorted, then alembic version
  local side="$1" query
  query="$("$side" psql -X -At -v ON_ERROR_STOP=1 -c "$COUNT_SQL_GEN")"
  "$side" psql -X -At -F '|' -v ON_ERROR_STOP=1 -c "$query" | sort
  echo "alembic_version|$("$side" psql -X -At -c 'SELECT string_agg(version_num, $$,$$) FROM alembic_version' 2>/dev/null || echo none)"
}

dst_tables() {
  dst psql -X -At -v ON_ERROR_STOP=1 -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
}

major() { sed -n 's/^\([0-9]*\).*/\1/p'; }

cmd_check() {
  local sv dv
  sv="$(src psql -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version' | major)"
  dv="$(dst psql -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version' | major)"
  echo "neon postgres: $sv   vps postgres: $dv   (host $SRC_HOST, db $SRC_DB)"
  if (( sv > dv )); then
    echo "FAIL: Neon is newer than the VPS server; change the db image to pgvector/pgvector:pg$sv" >&2
    return 1
  fi
  local ext missing=""
  for ext in $(src psql -X -At -v ON_ERROR_STOP=1 -c \
      "SELECT extname FROM pg_extension WHERE extname <> 'plpgsql' ORDER BY 1"); do
    [[ "$(dst psql -X -At -c "SELECT count(*) FROM pg_available_extensions WHERE name = '$ext'")" == 1 ]] \
      || missing="$missing $ext"
  done
  if [[ -n "$missing" ]]; then
    echo "FAIL: Neon uses extensions the VPS server does not have:$missing" >&2
    return 1
  fi
  echo "extensions: all available on the vps"
  echo "vps database tables: $(dst_tables) (must be 0 before restore)"
  echo "neon size: $(src psql -X -At -c 'SELECT pg_size_pretty(pg_database_size(current_database()))')"
  mkdir -p "$BACKUP_DIR"
  echo "free disk at $BACKUP_DIR: $(df -h "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
  echo "OK"
}

cmd_dump() {
  local stamp file
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP_DIR"
  file="$BACKUP_DIR/neon-$stamp.dump"
  umask 077
  src pg_dump -Fc --no-owner --no-privileges > "$file.part"
  pg pg_restore --list < "$file.part" > /dev/null
  mv "$file.part" "$file"
  echo "dump: $file ($(du -h "$file" | cut -f1))"
}

cmd_restore() {
  local file="${1:-}" n
  [[ -f "$file" ]] || { echo "usage: db_move.sh restore <dump file>" >&2; return 2; }
  n="$(dst_tables)"
  if [[ "$n" != 0 ]]; then
    echo "refusing: the VPS database already has $n tables (restore only into an empty one;" \
      "see the runbook for starting it afresh)" >&2
    return 1
  fi
  # -d is required: without it pg_restore prints SQL instead of restoring.
  dst sh -c 'exec pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
    -d "$PGDATABASE"' < "$file" 2>&1 || {
      echo "restore failed: nothing was kept (single transaction)" >&2; return 1; }
  dst psql -X -q -v ON_ERROR_STOP=1 -c 'ANALYZE' > /dev/null
  echo "restored $file: $(dst_tables) tables"
}

cmd_verify() {
  local a b
  a="$(counts src)"
  b="$(counts dst)"
  if [[ "$a" == "$b" ]]; then
    echo "$a" | awk -F'|' '{printf "  %-40s %s\n", $1, $2}'
    echo "OK: $(echo "$a" | wc -l | tr -d ' ') lines identical (row counts per table + alembic version)"
    return 0
  fi
  echo "DIFFERENT (left: neon, right: vps):" >&2
  diff <(echo "$a") <(echo "$b") >&2 || true
  return 1
}

cmd_backup() {
  local stamp file
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP_DIR"
  file="$BACKUP_DIR/agentx-$stamp.dump"
  umask 077
  dst pg_dump -Fc < /dev/null > "$file.part"
  pg pg_restore --list < "$file.part" > /dev/null
  mv "$file.part" "$file"
  # Keep the newest $KEEP nightly backups; the neon-*.dump copies are never deleted here.
  ls -1t "$BACKUP_DIR"/agentx-*.dump | tail -n +"$(( KEEP + 1 ))" | while IFS= read -r old; do
    rm -f -- "$old"
  done
  echo "backup: $file ($(du -h "$file" | cut -f1)); kept $(ls -1 "$BACKUP_DIR"/agentx-*.dump | wc -l | tr -d ' ')"
}

case "${1:-}" in
  check) cmd_check ;;
  dump) cmd_dump ;;
  restore) shift; cmd_restore "$@" ;;
  verify) cmd_verify ;;
  backup) cmd_backup ;;
  *) echo "usage: db_move.sh check|dump|restore <file>|verify|backup" >&2; exit 2 ;;
esac
