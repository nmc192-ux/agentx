#!/usr/bin/env bash
# Copy the AgentX database from Neon to the VPS Postgres, check the copy, and take nightly
# backups (DB-1). Runbook: platform/docs/execution/db_move_runbook.md. Run on the VPS as `deploy`:
#
#   cd /opt/agentx && bash db_move.sh check            # versions, target empty?, disk (changes nothing)
#   cd /opt/agentx && bash db_move.sh dump             # Neon -> /var/backups/agentx/neon-<time>.dump
#   cd /opt/agentx && bash db_move.sh restore <file>   # into the EMPTY VPS database, all or nothing
#   cd /opt/agentx && bash db_move.sh verify           # exact row counts, Neon vs VPS, every table
#   cd /opt/agentx && bash db_move.sh backup           # VPS -> /var/backups/agentx/agentx-<time>.dump
#                                                      # (+ media-<time>.tar.gz of the agentx_media volume)
#   cd /opt/agentx && bash db_move.sh restore-test     # newest backup -> throwaway database, compare, drop
#
# Every Postgres tool runs from the `db` image (pg17 tools, so they can read a Neon server of
# version 17 or older). Neon is only ever read: pg_dump and SELECT count(*). The Neon password is
# read from api.env and handed to the tool on stdin, never on a command line or the screen. The
# VPS database is reached over the running container's local socket (trusted by the postgres
# image). Tools that talk to Neon run in a throwaway container of the same image instead
# (SR-1): it never sees db.env, and the VPS's CA bundle is mounted into it so the connection is
# `sslmode=verify-full` (the postgres image ships no CA certificates; `require` alone would
# encrypt to whoever answered, and an interceptor could relay the login and read the whole dump).
#
# Local rehearsal (tests/infrastructure/test_db_move.py): PG_RUN=native runs the same commands on
# this machine instead of in the container; SRC_* point the "Neon" side at a scratch database.
set -euo pipefail

cd "${AGENTX_DIR:-/opt/agentx}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/agentx}"
KEEP="${KEEP:-14}"
# Images (Layer 1 S4): the agentx_media volume is archived next to the dump, if the volume exists.
# Archives are big, so fewer are kept. PG_RUN=native reads MEDIA_DIR (a folder) instead.
MEDIA_VOLUME="${MEDIA_VOLUME:-agentx_media}"
MEDIA_KEEP="${MEDIA_KEEP:-3}"
SECRETS="${AGENTX_SECRETS_FILE:-/etc/agentx/api.env}"

env_value() {  # env_value FILE NAME -> last value of NAME in FILE, quotes removed
  local v
  v="$(sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -n 1)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

# backup and restore-test also leave backup.json / restore_test.json here for BRUNO (TF-3):
# only ok/fail and the time, never a file name, size or error text.
STATUS_DIR="${AGENTX_STATUS_DIR:-$(env_value compose.env AGENTX_STATUS_DIR)}"
STATUS_DIR="${STATUS_DIR:-/opt/agentx/status}"
# status_record NAME JSON: a small record for the founders BRUNO and QUINN (TF-3), written whole
# then renamed (never half a file) and readable by the scheduler, which mounts $STATUS_DIR
# read-only. Best effort: a record that cannot be written never fails the run.
status_record() {
  (umask 022 && mkdir -p "$STATUS_DIR" && printf '%s\n' "$2" > "$STATUS_DIR/.$1.json.tmp" \
    && chmod 644 "$STATUS_DIR/.$1.json.tmp" && mv -f "$STATUS_DIR/.$1.json.tmp" "$STATUS_DIR/$1.json") 2>/dev/null \
    || echo "warning: could not write $STATUS_DIR/$1.json" >&2
}

# The Neon side. Since the early launch (EL-3) settings.env names the VPS database, not Neon,
# so Neon is only ever reached when SRC_HOST is given on the command line: the direct endpoint,
# not the "-pooler" one (Neon's pooler is PgBouncer in transaction mode; pg_dump wants a plain session).
SRC_HOST="${SRC_HOST:-}"
SRC_PORT="${SRC_PORT:-5432}"
SRC_USER="${SRC_USER:-neondb_owner}"
SRC_DB="${SRC_DB:-neondb}"
SRC_SSLMODE="${SRC_SSLMODE:-verify-full}"
SRC_SSLROOTCERT="${SRC_SSLROOTCERT:-/etc/ssl/certs/ca-certificates.crt}"   # the VPS's CA bundle
DB_IMAGE="${DB_IMAGE:-pgvector/pgvector:pg17}"   # must equal the db service image in docker-compose.yml
# Only the commands that read Neon need it (backup and restore-test never touch Neon).
need_src() { [[ -n "$SRC_HOST" ]] || { echo "no SRC_HOST: give Neon's direct endpoint, e.g. SRC_HOST=ep-....neon.tech" >&2; exit 1; }; }

# restore-test (LR-2): the throwaway database, and how old the newest backup may be.
RESTORE_TEST_DB="${RESTORE_TEST_DB:-agentx_restore_test}"
MAX_BACKUP_AGE_H="${MAX_BACKUP_AGE_H:-26}"
RESTORE_MIN_SHARE="${RESTORE_MIN_SHARE:-50}"   # backup must hold >= this % of the live rows
RESTORE_DISK_FACTOR="${RESTORE_DISK_FACTOR:-10}"   # data disk must have >= this x the dump's size free

pg() {  # run a command inside the running db container (VPS side)
  if [[ "${PG_RUN:-container}" == native ]]; then
    "$@"
  else
    docker compose --env-file compose.env --profile db exec -T db "$@"
  fi
}

pg_src() {  # run a command that talks to Neon: a throwaway container with the CA bundle, no db.env
  if [[ "${PG_RUN:-container}" == native ]]; then
    "$@"
  else
    [[ -f "$SRC_SSLROOTCERT" ]] || { echo "no CA bundle at $SRC_SSLROOTCERT (apt install ca-certificates)" >&2; return 1; }
    docker run --rm -i -v "$SRC_SSLROOTCERT:/etc/agentx-ca.crt:ro" "$DB_IMAGE" "$@"
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
  # The root cert is named only when the mode verifies it (verify-ca / verify-full).
  local rootcert=()
  if [[ "$SRC_SSLMODE" == verify-* ]]; then
    if [[ "${PG_RUN:-container}" == native ]]; then rootcert=(PGSSLROOTCERT="$SRC_SSLROOTCERT")
    else rootcert=(PGSSLROOTCERT=/etc/agentx-ca.crt); fi
  fi
  src_password | pg_src env PGHOST="$SRC_HOST" PGPORT="$SRC_PORT" PGUSER="$SRC_USER" \
    PGDATABASE="$SRC_DB" PGSSLMODE="$SRC_SSLMODE" ${rootcert[@]+"${rootcert[@]}"} PGCONNECT_TIMEOUT=20 \
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

# tst TOOL ARGS... : the same, but against the throwaway restore-test database.
tst() {
  pg sh -c 'export PGUSER="$POSTGRES_USER" PGDATABASE="$1"; shift; exec "$@"' sh "$RESTORE_TEST_DB" "$@"
}

dst_tables() {
  dst psql -X -At -v ON_ERROR_STOP=1 -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
}

major() { sed -n 's/^\([0-9]*\).*/\1/p'; }

cmd_check() {
  need_src
  local sv dv
  sv="$(src psql -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version' | major)"
  dv="$(dst psql -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version' | major)"
  echo "neon postgres: $sv   vps postgres: $dv   (host $SRC_HOST, db $SRC_DB, sslmode $SRC_SSLMODE)"
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

# A dump that died halfway (power, OOM, kill) leaves a .part file that nothing else deletes
# and that the retention loop never counts; sweep the stale ones before writing a new dump.
sweep_parts() {
  find "$BACKUP_DIR" -maxdepth 1 \( -name '*.dump.part' -o -name 'media-*.tar.gz.part' \) -mmin +1440 -delete 2>/dev/null || true
}

# media_exists: is there a media volume (or, natively, a MEDIA_DIR folder) to archive?
media_exists() {
  if [[ "${PG_RUN:-container}" == native ]]; then
    [[ -n "${MEDIA_DIR:-}" && -d "${MEDIA_DIR:-}" ]]
  else
    docker volume inspect "$MEDIA_VOLUME" > /dev/null 2>&1
  fi
}

# media_tar: the media files as a gzipped tar on stdout. The volume is mounted read-only into a
# throwaway container of the db image (already on the VPS); nothing else is mounted into it.
media_tar() {
  if [[ "${PG_RUN:-container}" == native ]]; then
    tar -C "$MEDIA_DIR" -czf - .
  else
    docker run --rm --network none -v "$MEDIA_VOLUME:/media:ro" "$DB_IMAGE" tar -C /media -czf - .
  fi
}

# media_backup STAMP: archive the images, check the archive reads back, keep the newest MEDIA_KEEP.
media_backup() {
  local file="$BACKUP_DIR/media-$1.tar.gz"
  if ! media_exists; then
    echo "media: no $MEDIA_VOLUME volume; nothing to archive"
    return 0
  fi
  media_tar < /dev/null > "$file.part" || { rm -f -- "$file.part"; return 1; }
  tar -tzf "$file.part" > /dev/null || { rm -f -- "$file.part"; return 1; }
  mv "$file.part" "$file"
  ls -1t "$BACKUP_DIR"/media-*.tar.gz | tail -n +"$(( MEDIA_KEEP + 1 ))" | while IFS= read -r old; do
    rm -f -- "$old"
  done
  echo "media: $file ($(du -h "$file" | cut -f1)); kept $(ls -1 "$BACKUP_DIR"/media-*.tar.gz | wc -l | tr -d ' ')"
}

cmd_dump() {
  need_src
  local stamp file
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP_DIR"
  sweep_parts
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
  need_src
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
  sweep_parts
  umask 077
  dst pg_dump -Fc < /dev/null > "$file.part"
  pg pg_restore --list < "$file.part" > /dev/null
  mv "$file.part" "$file"
  # Keep the newest $KEEP nightly backups; the neon-*.dump copies are never deleted here.
  ls -1t "$BACKUP_DIR"/agentx-*.dump | tail -n +"$(( KEEP + 1 ))" | while IFS= read -r old; do
    rm -f -- "$old"
  done
  echo "backup: $file ($(du -h "$file" | cut -f1)); kept $(ls -1 "$BACKUP_DIR"/agentx-*.dump | wc -l | tr -d ' ')"
  # The database dump is safe on disk first; a media archive that fails marks the run failed.
  if ! media_backup "$stamp"; then
    status_record backup "$(printf '{"ok": false, "finished_at": "%s"}' "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
    echo "ALERT: backup of the images (media volume) failed; the database dump is fine" >&2
    return 1
  fi
  status_record backup "$(printf '{"ok": true, "finished_at": "%s"}' "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
}

# restore-test: prove last night's backup can be loaded. Newest agentx-*.dump -> a throwaway
# database on the same server -> table list, alembic version and row counts compared with the
# live database -> throwaway dropped (also on failure). The live database is only read.
# Any failure prints one "ALERT: ..." line on stderr and exits 1; the result is also written to
# $BACKUP_DIR/restore-test.status ("ok|fail <utc time> <detail>") for the watchdog (LR-3).
restore_status() {  # restore_status ok|fail DETAIL (written whole, then renamed: the watchdog never sees a half line)
  mkdir -p "$BACKUP_DIR"
  printf '%s %s %s\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" > "$BACKUP_DIR/restore-test.status.tmp" \
    && mv -f "$BACKUP_DIR/restore-test.status.tmp" "$BACKUP_DIR/restore-test.status"
  local ok=false
  [[ "$1" == ok ]] && ok=true
  status_record restore_test "$(printf '{"ok": %s, "finished_at": "%s"}' "$ok" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
}

RT_REPORTED=""
restore_fail() {
  RT_REPORTED=1
  echo "ALERT: backup restore-test failed: $1" >&2
  restore_status fail "$1"
  return 1
}

restore_test_exit() {  # EXIT trap: always drop the throwaway database; never fail silently
  local rc=$?
  drop_test_db > /dev/null 2>&1 || true
  if (( rc != 0 )) && [[ -z "$RT_REPORTED" ]]; then
    restore_fail "stopped unexpectedly (exit $rc); see the lines above" || true
  fi
  exit "$rc"
}

drop_test_db() {
  dst psql -X -q -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $RESTORE_TEST_DB WITH (FORCE)" > /dev/null
}

total_rows() { awk -F'|' '$1 != "alembic_version" {s += $2} END {print s + 0}'; }

# data_disk_short FILE -> a reason when the server's data disk may not hold a restored copy of
# FILE (a compressed dump unpacks to several times its size, plus WAL), empty when there is room.
# The throwaway copy lives on the same disk as the live database; filling it would stop the live
# database, so the test refuses instead. If the free space cannot be read the guard stands aside
# (the watchdog's disk check still applies) and says so.
data_disk_short() {
  local datadir free need
  datadir="$(dst psql -X -At -c 'SHOW data_directory' 2>/dev/null || true)"
  free="$([[ -n "$datadir" ]] && pg df -Pk "$datadir" 2>/dev/null | awk 'NR == 2 {print $4}' || true)"
  if ! [[ "$free" =~ ^[0-9]+$ ]]; then
    echo "note: could not read the free space of the data disk; restoring without that check" >&2
    return 0
  fi
  need=$(( $(wc -c < "$1" | tr -d ' ') * RESTORE_DISK_FACTOR / 1024 ))
  if (( free < need )); then
    printf '%s KB free on the data disk, %s KB wanted (%s x the dump; RESTORE_DISK_FACTOR)' \
      "$free" "$need" "$RESTORE_DISK_FACTOR"
  fi
  return 0
}

cmd_restore_test() {
  local file live a b
  # The name goes into SQL unquoted, and must never be the live database.
  if [[ ! "$RESTORE_TEST_DB" =~ ^agentx_restore_test[a-z0-9_]*$ ]]; then
    restore_fail "refusing target database '$RESTORE_TEST_DB' (must start with agentx_restore_test)"
    return 1
  fi
  live="$(dst printenv PGDATABASE)"
  if [[ -z "$live" || "$live" == "$RESTORE_TEST_DB" ]]; then
    restore_fail "refusing: target '$RESTORE_TEST_DB' is the live database"
    return 1
  fi

  [[ -d "$BACKUP_DIR" ]] || { restore_fail "no backup folder $BACKUP_DIR"; return 1; }
  file="$(ls -1t "$BACKUP_DIR"/agentx-*.dump 2>/dev/null | head -n 1 || true)"
  [[ -n "$file" ]] || { restore_fail "no agentx-*.dump in $BACKUP_DIR"; return 1; }
  [[ -s "$file" ]] || { restore_fail "newest backup $file is empty"; return 1; }
  if [[ -n "$(find "$file" -mmin +"$(( MAX_BACKUP_AGE_H * 60 ))")" ]]; then
    restore_fail "newest backup $file is older than $MAX_BACKUP_AGE_H h (is the nightly backup running?)"
    return 1
  fi
  pg pg_restore --list < "$file" > /dev/null 2>&1 \
    || { restore_fail "newest backup $file is not a readable dump (corrupt or cut short)"; return 1; }
  local short
  short="$(data_disk_short "$file")"
  [[ -z "$short" ]] || { restore_fail "not enough free disk for a restored copy: $short"; return 1; }

  trap restore_test_exit EXIT
  drop_test_db
  dst psql -X -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE $RESTORE_TEST_DB" > /dev/null
  # Only pg_restore's complaints are kept (stderr); the first one goes into the alert.
  local err
  if ! err="$(tst sh -c 'exec pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
      -d "$PGDATABASE"' < "$file" 2>&1 > /dev/null)"; then
    restore_fail "pg_restore of $file stopped: $(printf '%s\n' "$err" | grep -m1 'error' | cut -c1-160)"
    return 1
  fi

  a="$(counts tst)"
  b="$(counts dst)"
  echo "  table                                    backup     live"
  awk -F'|' 'NR == FNR {live[$1] = $2; next}
    {printf "  %-40s %6s %8s\n", $1, $2, ($1 in live ? live[$1] : "-"); delete live[$1]}
    END {for (t in live) printf "  %-40s %6s %8s\n", t, "-", live[t]}' <(echo "$b") <(echo "$a")
  if [[ "$(echo "$a" | cut -d'|' -f1)" != "$(echo "$b" | cut -d'|' -f1)" ]]; then
    restore_fail "the backup's tables differ from the live database's (see the list above)"
    return 1
  fi
  if [[ "$(echo "$a" | grep '^alembic_version|')" != "$(echo "$b" | grep '^alembic_version|')" ]]; then
    restore_fail "the backup is from another migration version than the live database"
    return 1
  fi
  local na nb
  na="$(echo "$a" | total_rows)"
  nb="$(echo "$b" | total_rows)"
  if (( nb > 0 && na * 100 < nb * RESTORE_MIN_SHARE )); then
    restore_fail "the backup holds $na rows, the live database $nb (under $RESTORE_MIN_SHARE %)"
    return 1
  fi
  restore_status ok "$(basename "$file") $(echo "$a" | grep -vc '^alembic_version|') tables $na rows"
  echo "OK: restore-test $(basename "$file"): $(echo "$a" | grep -vc '^alembic_version|') tables," \
    "$na rows (live $nb); throwaway database dropped"
}

case "${1:-}" in
  check) cmd_check ;;
  dump) cmd_dump ;;
  restore) shift; cmd_restore "$@" ;;
  verify) cmd_verify ;;
  backup) cmd_backup ;;
  restore-test) cmd_restore_test ;;
  *) echo "usage: db_move.sh check|dump|restore <file>|verify|backup|restore-test" >&2; exit 2 ;;
esac
