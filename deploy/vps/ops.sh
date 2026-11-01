#!/usr/bin/env bash
# AgentX VPS ops: the server side of the "VPS ops" workflow (.github/workflows/vps-ops.yml).
# Runs on the VPS as `deploy`, never with sudo, and only touches what `deploy` owns:
# /opt/agentx (ops.env, alerts.env), its own crontab, and the db container through docker.
#
#   cd /opt/agentx && bash ops.sh status          # what is running and switched on (changes nothing)
#   cd /opt/agentx && bash ops.sh welcomes on     # H50 step 2: founder welcomes on (rolls api-1, api-2, scheduler)
#   cd /opt/agentx && bash ops.sh welcomes off    # H50 step 4: and off again
#   cd /opt/agentx && bash ops.sh disk-report     # where the disk space goes (changes nothing)
#   cd /opt/agentx && bash ops.sh disk-cleanup    # old AgentX images + dangling layers only
#   cd /opt/agentx && bash ops.sh build-cache-clear  # Docker build cache only (next build is slower once)
#   cd /opt/agentx && bash ops.sh heartbeat-report  # the founders' last heartbeat + welcome log lines
#   cd /opt/agentx && bash ops.sh alerts-setup    # H37 step 3: ntfy topic, watchdog cron, first run
#   cd /opt/agentx && bash ops.sh alerts-test     # one test notification to the phone
#   cd /opt/agentx && bash ops.sh import-report   # H47 steps 1-4: backup, Neon dump, side db, DRY RUN
#   cd /opt/agentx && bash ops.sh import-apply    # H47 steps 5-6: apply, release reservations, tidy, backup
#   cd /opt/agentx && bash ops.sh test-accounts-report  # H25 step 1: list + DRY RUN (changes nothing)
#   cd /opt/agentx && bash ops.sh test-accounts-remove  # H25 step 2: backup, remove exactly the report's list
#
# Switches live in /opt/agentx/ops.env (owner deploy, chmod 600), which docker-compose.yml loads
# AFTER settings.env and BEFORE /etc/agentx/api.env: a line DrJ writes by hand in api.env always
# wins, so api.env stays the manual override. Only the names in OPS_SWITCHES can be written.
#
# import-report reads Neon's DIRECT host from NEON_HOST and the Neon password from stdin (one
# line); the password goes into a temporary chmod-600 file for db_move.sh and is removed on exit.
# It is never printed and never put on a command line.
#
# test-accounts-report runs scripts/remove_test_accounts.py (through vps_test_accounts.py, which
# takes the connection from the app settings) as `show` and as a dry run, and keeps the addresses
# the dry run would remove in test_accounts.dids. test-accounts-remove takes a backup and then
# removes exactly those addresses (named with --did, so a test account that appeared after the
# report is never touched); the script re-checks every rule and refuses the whole run if one
# account fails. The list is used once and expires after a day.
#
# Pinned by platform/tests/infrastructure/test_vps_ops.py.
set -euo pipefail

cd "${AGENTX_DIR:-/opt/agentx}"
OPS_ENV="${AGENTX_OPS_ENV:-$PWD/ops.env}"
SECRETS="${AGENTX_SECRETS_FILE:-/etc/agentx/api.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/agentx}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
OLD_DB="agentx_old"
OPS_SWITCHES="FOUNDER_WELCOMES_ENABLED"
NEON_TMP=""
TEST_DIDS="${AGENTX_TEST_DIDS:-$PWD/test_accounts.dids}"
TEST_DIDS_MAX_AGE_MIN=1440
PROJECT=agentx

dc() { docker compose --env-file compose.env "$@"; }
say() { printf '%s\n' "$*"; }
die() { printf 'ops: %s\n' "$*" >&2; exit 1; }

env_value() {  # env_value FILE NAME -> last value of NAME in FILE, quotes removed (never sourced)
  local v
  v="$(sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -n 1)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

is_switch() { [[ " $OPS_SWITCHES " == *" $1 "* ]]; }

set_switch() {  # set_switch NAME VALUE: rewrite ops.env whole, then rename (never half a file)
  local name="$1" value="$2" tmp
  is_switch "$name" || die "$name is not an ops switch"
  [[ "$value" =~ ^(true|false)$ ]] || die "switch values are true or false"
  tmp="$(mktemp "$OPS_ENV.XXXXXX")"
  chmod 600 "$tmp"
  {
    echo "# Written by ops.sh (VPS ops workflow). Switches only, never secrets. api.env wins."
    if [[ -f "$OPS_ENV" ]]; then
      grep -E '^[A-Z_]+=(true|false)$' "$OPS_ENV" | while IFS='=' read -r k v; do
        if is_switch "$k" && [[ "$k" != "$name" ]]; then echo "$k=$v"; fi
      done
    fi
    echo "$name=$value"
  } > "$tmp"
  mv -f "$tmp" "$OPS_ENV"
}

scheduler_running() {
  [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=scheduler" --filter status=running)" ]]
}

wait_healthy() {  # same rule as deploy.sh: one API container healthy before the next is replaced
  local svc="$1" id status waited=0
  id="$(dc ps -q "$svc")"
  [[ -n "$id" ]] || die "$svc: no container"
  while (( waited < HEALTH_TIMEOUT )); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo missing)"
    case "$status" in
      healthy) say "$svc healthy after ${waited}s"; return 0 ;;
      unhealthy|missing) break ;;
    esac
    sleep 3
    waited=$(( waited + 3 ))
  done
  dc logs --tail 30 "$svc" >&2 || true
  die "$svc did not become healthy (last status: ${status:-unknown})"
}

roll() {  # recreate api-1, api-2 one at a time (same image), then the scheduler if it ran
  local had_scheduler=no svc
  if scheduler_running; then had_scheduler=yes; fi
  for svc in api-1 api-2; do
    dc up -d --no-deps --force-recreate "$svc"
    wait_healthy "$svc"
  done
  if [[ "$had_scheduler" == yes ]]; then
    dc --profile scheduler up -d --no-deps --force-recreate scheduler
    say "scheduler recreated"
  else
    say "scheduler was not running; left stopped"
  fi
}

effective() {  # effective NAME -> the value a container sees (api.env beats ops.env)
  local v
  v="$(env_value "$SECRETS" "$1")"
  [[ -n "$v" ]] || v="$(env_value "$OPS_ENV" "$1")"
  printf '%s' "${v:-unset}"
}

cmd_status() {
  say "== containers"
  dc ps --format '{{.Service}}  {{.State}}  {{.Status}}' 2>/dev/null || dc ps
  say "== image tag: $(env_value compose.env IMAGE_TAG)"
  say "== switches (api.env beats ops.env)"
  local name
  for name in FOUNDER_HEARTBEAT_ENABLED FOUNDER_WELCOMES_ENABLED FOUNDER_LLM_PROVIDER; do
    say "$name=$(effective "$name")"
  done
  say "== alerts"
  if [[ -f "$PWD/alerts.env" ]]; then say "alerts.env: /opt/agentx/alerts.env"; \
  elif [[ -r /etc/agentx/alerts.env ]]; then say "alerts.env: /etc/agentx/alerts.env"; \
  else say "alerts.env: none"; fi
  if crontab -l 2>/dev/null | grep -q 'watchdog.sh'; then say "watchdog cron: installed"; else say "watchdog cron: missing"; fi
  tail -n 8 "$BACKUP_DIR/watchdog.log" 2>/dev/null || true
  say "== newest backup"
  ls -1t "$BACKUP_DIR"/agentx-*.dump 2>/dev/null | head -n 1 || say "none"
  say "== side database $OLD_DB"
  if old_db_exists; then say "present"; else say "absent"; fi
}

cmd_welcomes() {
  local value
  case "${1:-}" in
    on) value=true ;;
    off) value=false ;;
    *) die "usage: ops.sh welcomes on|off" ;;
  esac
  if [[ -n "$(env_value "$SECRETS" FOUNDER_WELCOMES_ENABLED)" ]]; then
    die "api.env sets FOUNDER_WELCOMES_ENABLED itself, so ops.env would be ignored; change it there"
  fi
  [[ "$(effective FOUNDER_HEARTBEAT_ENABLED)" =~ ^(1|true|yes|TRUE|True)$ ]] \
    || say "note: FOUNDER_HEARTBEAT_ENABLED is not on, so no welcomes are sent until it is (H13)"
  set_switch FOUNDER_WELCOMES_ENABLED "$value"
  roll
  say "api-1 sees FOUNDER_WELCOMES_ENABLED=$(dc exec -T api-1 printenv FOUNDER_WELCOMES_ENABLED 2>/dev/null || echo unset)"
  say "welcomes $1"
}

alerts_file() {  # the alerts file the watchdog should read: DrJ's /etc copy if he made one
  if [[ -r /etc/agentx/alerts.env ]]; then echo /etc/agentx/alerts.env; else echo "$PWD/alerts.env"; fi
}

cmd_alerts_setup() {
  local file topic="" line
  [[ -f watchdog.sh ]] || die "watchdog.sh is not in /opt/agentx"
  mkdir -p "$BACKUP_DIR"
  file="$(alerts_file)"
  if [[ "$file" == "$PWD/alerts.env" && -z "$(env_value "$file" NTFY_URL)" ]]; then
    topic="agentx-$(openssl rand -hex 12)"
    (umask 077 && printf 'NTFY_URL=https://ntfy.sh/%s\nSLACK_WEBHOOK_URL=\n' "$topic" > "$file.tmp")
    mv -f "$file.tmp" "$file"
  fi
  chmod 600 "$file" 2>/dev/null || true
  line="*/5 * * * * cd /opt/agentx && ALERTS_ENV=$file bash watchdog.sh >> $BACKUP_DIR/watchdog.log 2>&1"
  { crontab -l 2>/dev/null | grep -v 'watchdog.sh' || true; echo "$line"; } | crontab -
  say "watchdog cron installed (every 5 minutes, alerts from $file)"
  say "== first watchdog run"
  ALERTS_ENV="$file" bash watchdog.sh || say "(at least one check is bad; see above)"
  if [[ -n "$topic" ]]; then
    # The one line the workflow lifts into the run summary and masks in the log.
    say "NTFY_TOPIC=$topic"
  else
    say "alerts file already had a topic; kept it"
  fi
  send_test "$file" "AgentX alerts are set up on $(hostname -s). You will hear here when the API, scheduler, backups or disk go wrong."
}

send_test() {  # send_test FILE MESSAGE: one ntfy message; the URL is never printed
  local url
  url="$(env_value "$1" NTFY_URL)"
  [[ -n "$url" ]] || die "no NTFY_URL in $1"
  if curl -sf --max-time 15 -H "Title: AgentX alerts" -d "$2" "$url" >/dev/null; then
    say "test notification sent"
  else
    die "could not reach ntfy"
  fi
}

cmd_alerts_test() { send_test "$(alerts_file)" "Test from the AgentX watchdog on $(hostname -s): alerts reach this phone."; }

old_db_exists() {
  [[ "$(dc --profile db exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='$OLD_DB'\"" 2>/dev/null)" == 1 ]]
}

cmd_import_report() {
  local host="${NEON_HOST:-}" password dump
  [[ "$host" =~ ^ep-[a-z0-9-]+\.[a-z0-9.-]+\.neon\.tech$ ]] || die "NEON_HOST must be Neon's direct host (ep-....neon.tech)"
  [[ "$host" != *-pooler* ]] || die "NEON_HOST is the -pooler host; give the direct one"
  IFS= read -r password || true
  # A pasted secret often carries a line ending, spaces or quotes, or is the whole connection
  # string; Neon passwords have none of those. Keep only the password itself.
  password="${password//$'\r'/}"
  if [[ "$password" == postgres*://*:*@* ]]; then password="${password#*://*:}"; password="${password%%@*}"; fi
  password="${password#"${password%%[![:space:]\"\']*}"}"
  password="${password%"${password##*[![:space:]\"\']}"}"
  [[ -n "$password" ]] || die "no Neon password on stdin"
  # Never the password: only its shape, so a wrong paste can be told apart from a wrong value.
  say "neon endpoint: ${host%%.*}; password: ${#password} characters, npg_ prefix: $([[ "$password" == npg_* ]] && echo yes || echo no)"
  say "== 1. backup of the live database"
  bash db_move.sh backup
  say "== 2. dump Neon (read only)"
  # The password file is global (NEON_TMP) so the EXIT trap still sees it after this function
  # returns or fails; any file a crashed earlier run left behind is removed first.
  rm -f "$PWD"/.neon.env.*
  NEON_TMP="$(mktemp "$PWD/.neon.env.XXXXXX")"
  trap 'rm -f "$NEON_TMP"' EXIT
  chmod 600 "$NEON_TMP"
  printf 'POSTGRES_PASSWORD=%s\n' "$password" > "$NEON_TMP"
  unset password
  AGENTX_SECRETS_FILE="$NEON_TMP" SRC_HOST="$host" bash db_move.sh dump
  rm -f "$NEON_TMP"
  dump="$(ls -1t "$BACKUP_DIR"/neon-*.dump | head -n 1)"
  say "dump: $(basename "$dump")"
  say "== 3. restore into the side database $OLD_DB (the live database is not touched)"
  dc --profile db exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $OLD_DB && createdb -U \"\$POSTGRES_USER\" $OLD_DB"
  dc --profile db exec -T db sh -c "exec pg_restore --no-owner --no-privileges --single-transaction --exit-on-error -U \"\$POSTGRES_USER\" -d $OLD_DB" < "$dump"
  say "== 4. import report (DRY RUN, changes nothing)"
  dc --profile migrate run --rm migrate python scripts/import_old_data.py --old-db "$OLD_DB"
}

cmd_import_apply() {
  old_db_exists || die "no $OLD_DB database: run import-report first"
  say "== 5. apply"
  dc --profile migrate run --rm migrate python scripts/import_old_data.py --old-db "$OLD_DB" --apply
  say "== 6. release leftover reservations, drop $OLD_DB, fresh backup"
  dc --profile migrate run --rm migrate python scripts/reserve_dids.py release --all
  dc --profile db exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" $OLD_DB"
  bash db_move.sh backup
}

disk_summary() {
  say "== disk"
  df -h / "$BACKUP_DIR" 2>/dev/null | awk 'NR==1 || !seen[$0]++'
  say "== docker"
  docker system df 2>/dev/null || true
}

cmd_disk_report() {  # changes nothing
  disk_summary
  say "== AgentX images (current tag first is kept, plus the previous one for rollback)"
  docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}  {{.CreatedSince}}' \
    "$(env_value compose.env AGENTX_IMAGE)" 2>/dev/null || true
  say "== dangling images: $(docker images -q -f dangling=true | wc -l)"
  say "== backups folder"
  du -sh "$BACKUP_DIR" 2>/dev/null || true
  ls -1t "$BACKUP_DIR" 2>/dev/null | head -n 30 | while read -r f; do
    say "$(du -h "$BACKUP_DIR/$f" | cut -f1)  $f"
  done
  say "== largest folders under /opt/agentx and /var/backups"
  du -xsh /opt/agentx /var/backups/* 2>/dev/null | sort -rh | head -n 10
}

cmd_disk_cleanup() {
  # Removes only: AgentX image tags other than the running one and the previous deploy's (kept
  # for rollback), and dangling images (untagged layers nobody uses). Never another project's
  # tagged images, containers, volumes or networks; never a backup.
  local repo current previous ref tag
  repo="$(env_value compose.env AGENTX_IMAGE)"
  current="$(env_value compose.env IMAGE_TAG)"
  [[ "$repo" == ghcr.io/*/agentx-platform && "$current" =~ ^[0-9a-f]{40}$ ]] \
    || die "compose.env has no AgentX image and tag; nothing removed"
  previous="$(sed -n 's/.*"previous": "\([0-9a-f]\{40\}\)".*/\1/p' status/deploy.json 2>/dev/null | head -n 1)"
  say "keeping $repo:$current (running) and ${previous:-no previous tag} (rollback)"
  disk_summary
  docker images --format '{{.Repository}}:{{.Tag}}' "$repo" | while read -r ref; do
    tag="${ref##*:}"
    if [[ "$tag" == "$current" || ( -n "$previous" && "$tag" == "$previous" ) ]]; then continue; fi
    if docker rmi "$ref" >/dev/null 2>&1; then say "removed $ref"; else say "kept $ref (in use)"; fi
  done
  docker image prune -f | tail -n 1
  say "== after"
  disk_summary
}

cmd_build_cache_clear() {
  # Docker's build cache (layers kept only to speed up the next `docker build` on this VPS; no
  # container, image, volume or backup uses it). The next build here starts from scratch once.
  say "== before"
  disk_summary
  docker builder prune -a -f | tail -n 1
  say "== after"
  disk_summary
}

cmd_heartbeat_report() {  # changes nothing: the founders' last heartbeat and its welcome lines
  say "== last founder heartbeat (scheduler_job_runs)"
  dc --profile db exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA' <<'SQL'
SELECT last_status, last_started_at, last_finished_at
  FROM scheduler_job_runs WHERE job_name = 'founder_heartbeat';
SELECT key || ': ' || value::text
  FROM scheduler_job_runs, jsonb_each(last_summary)
 WHERE job_name = 'founder_heartbeat'
   AND (key ILIKE '%welcom%' OR key IN ('enabled', 'skipped', 'llm_calls'))
 ORDER BY 1;
SQL
  say "== scheduler log, last 2 hours, welcome lines"
  dc --profile scheduler logs --since 2h scheduler 2>&1 | grep -iE 'welcom' | tail -n 40 || say "(none)"
}

test_accounts() {  # test_accounts ARGS...: the reviewed removal script, app database, in migrate
  dc --profile migrate run --rm migrate python scripts/vps_test_accounts.py "$@"
}

cmd_test_accounts_report() {  # changes nothing on the database
  local out tmp n
  rm -f "$TEST_DIDS"
  say "== 1. test accounts (reads only)"
  test_accounts show
  say "== 2. DRY RUN (changes nothing; this is what test-accounts-remove will do)"
  out="$(test_accounts remove)" || { printf '%s\n' "$out"; die "the dry run refused; nothing was changed and no list was kept"; }
  printf '%s\n' "$out"
  tmp="$(mktemp "$TEST_DIDS.XXXXXX")"
  chmod 600 "$tmp"
  printf '%s\n' "$out" | sed -n 's/^  \(did:agentx:[A-Za-z0-9._-]*\)  .*/\1/p' > "$tmp"
  n="$(wc -l < "$tmp" | tr -d ' ')"
  if [[ "$n" == 0 ]]; then
    rm -f "$tmp"
    say "== nothing to remove; test-accounts-remove has nothing to do"
    return 0
  fi
  grep -q "^DRY RUN: $n test account(s) would be removed" <<< "$out" \
    || { rm -f "$tmp"; die "the dry run's count does not match the $n addresses read; no list was kept"; }
  mv -f "$tmp" "$TEST_DIDS"
  say "== kept the $n address(es) above for test-accounts-remove (valid for 24 hours)"
}

cmd_test_accounts_remove() {
  local did dids=() args=()
  [[ -f "$TEST_DIDS" ]] || die "no list from test-accounts-report: run it first and read it"
  [[ -n "$(find "$TEST_DIDS" -mmin "-$TEST_DIDS_MAX_AGE_MIN" 2>/dev/null)" ]] \
    || { rm -f "$TEST_DIDS"; die "the test-accounts-report list is older than 24 hours: run the report again"; }
  while IFS= read -r did; do
    [[ "$did" =~ ^did:agentx:[A-Za-z0-9._-]+$ ]] || { rm -f "$TEST_DIDS"; die "the kept list is damaged: run the report again"; }
    dids+=("$did"); args+=(--did "$did")
  done < "$TEST_DIDS"
  (( ${#dids[@]} > 0 )) || { rm -f "$TEST_DIDS"; die "the kept list is empty: run the report again"; }
  rm -f "$TEST_DIDS"   # used once, whatever happens next
  say "== 1. fresh backup"
  bash db_move.sh backup
  say "== 2. remove ${#dids[@]} test account(s): ${dids[*]}"
  test_accounts remove "${args[@]}" --apply --by "DrJ (VPS ops)"
  say "== 3. check (should list none of the above)"
  test_accounts show
}

rm -f "$PWD"/.neon.env.* 2>/dev/null || true   # never leave a Neon password file behind

case "${1:-}" in
  status) cmd_status ;;
  heartbeat-report) cmd_heartbeat_report ;;
  build-cache-clear) cmd_build_cache_clear ;;
  disk-report) cmd_disk_report ;;
  disk-cleanup) cmd_disk_cleanup ;;
  welcomes) shift; cmd_welcomes "${1:-}" ;;
  alerts-setup) cmd_alerts_setup ;;
  alerts-test) cmd_alerts_test ;;
  import-report) cmd_import_report ;;
  import-apply) cmd_import_apply ;;
  test-accounts-report) cmd_test_accounts_report ;;
  test-accounts-remove) cmd_test_accounts_remove ;;
  *) echo "usage: ops.sh status|heartbeat-report|disk-report|disk-cleanup|build-cache-clear|welcomes on|off|alerts-setup|alerts-test|import-report|import-apply|test-accounts-report|test-accounts-remove" >&2; exit 2 ;;
esac
