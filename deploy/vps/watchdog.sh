#!/usr/bin/env bash
# AgentX watchdog (LR-3): free alerts when the VPS side of AgentX goes wrong. Runs on the VPS as
# `deploy` from cron every 5 minutes:
#
#   */5 * * * * cd /opt/agentx && bash watchdog.sh >> /var/backups/agentx/watchdog.log 2>&1
#
# Checks (each one is "ok" or "bad"):
#   api        GET $API_URL/health through Caddy answers 200
#   ready      GET $API_URL/health/ready answers 200 (the API reaches the database)
#   scheduler  the newest successful scheduler_job_runs row finished < SCHEDULER_MAX_MIN ago
#   backup     the newest $BACKUP_DIR/agentx-*.dump is < MAX_BACKUP_AGE_H old
#   restore    db_move.sh restore-test's status file does not say "fail" (and, once it exists,
#              is < MAX_BACKUP_AGE_H old: the nightly restore test is still running)
#   disk       the disk holding $BACKUP_DIR is < DISK_MAX_PCT % full
#
# An alert is sent only when a check changes state: once when it goes bad, once when it recovers.
# The last state of every check is kept in $STATE_FILE. If no message could be delivered, the
# state is not updated, so the next run tries again (that is a retry, not a flood).
#
# Where alerts go: /etc/agentx/alerts.env (ALERTS_ENV), read as plain NAME=value lines, never run:
#   NTFY_URL=https://ntfy.sh/<long random topic>     (phone app "ntfy", subscribe to the topic)
#   SLACK_WEBHOOK_URL=https://hooks.slack.com/...     (optional)
# With neither set, alerts are only written to the log. The URLs are never printed: the ntfy
# topic name is the only thing standing between a stranger and your alerts.
#
# "The whole VPS is gone" cannot be reported from the VPS itself: UptimeRobot (H37) watches
# $API_URL/health from outside.
#
# Local tests (tests/infrastructure/test_watchdog.py): PG_RUN=native runs psql on this machine
# instead of in the db container; fake curl/psql/df on PATH.
# Exit code: 0 all checks ok, 1 at least one check bad.
set -uo pipefail

cd "${AGENTX_DIR:-/opt/agentx}" || exit 2
API_URL="${API_URL:-https://api.agentx.social}"
API_URL="${API_URL%/}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/agentx}"
STATE_FILE="${STATE_FILE:-$BACKUP_DIR/watchdog.state}"
ALERTS_ENV="${ALERTS_ENV:-/etc/agentx/alerts.env}"
CHECKS="${CHECKS:-api ready scheduler backup restore disk}"
SCHEDULER_MAX_MIN="${SCHEDULER_MAX_MIN:-30}"
MAX_BACKUP_AGE_H="${MAX_BACKUP_AGE_H:-26}"
DISK_MAX_PCT="${DISK_MAX_PCT:-85}"
HOST_LABEL="${HOST_LABEL:-$(hostname -s 2>/dev/null || echo vps)}"

log() { printf '%s watchdog: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

env_value() {  # env_value FILE NAME -> last value of NAME in FILE, quotes removed (never sourced)
  local v
  v="$(sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -n 1)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

clean() {  # one printable line, at most 200 characters (text read from files or tools)
  tr -d '\r' | head -n 1 | tr -cd '[:print:]' | cut -c1-200
}

db_query() {  # db_query SQL -> one value from the VPS database
  if [[ "${PG_RUN:-container}" == native ]]; then
    psql -X -At -v ON_ERROR_STOP=1 -c "$1"
  else
    # shellcheck disable=SC2016  # expanded inside the container, where db.env is loaded
    docker compose --env-file compose.env --profile db exec -T db \
      sh -c 'exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$0"' "$1"
  fi
}

# Each check prints one line of detail and returns 0 (ok) or 1 (bad).
http_code() { curl -sS -o /dev/null -w '%{http_code}' --max-time 10 --retry 1 "$1" 2>/dev/null || true; }

check_api() {
  local code; code="$(http_code "$API_URL/health" | clean)"
  [[ "$code" == 200 ]] && { echo "$API_URL/health answers 200"; return 0; }
  echo "$API_URL/health answered ${code:-nothing} (want 200)"; return 1
}

check_ready() {
  local code; code="$(http_code "$API_URL/health/ready" | clean)"
  [[ "$code" == 200 ]] && { echo "$API_URL/health/ready answers 200"; return 0; }
  echo "$API_URL/health/ready answered ${code:-nothing} (want 200; the API cannot reach the database?)"; return 1
}

check_scheduler() {
  local age
  age="$(db_query "SELECT COALESCE(EXTRACT(EPOCH FROM now() - max(last_finished_at))::bigint, -1)
                     FROM scheduler_job_runs WHERE last_status = 'ok'" 2>/dev/null | clean)"
  if ! [[ "$age" =~ ^-?[0-9]+$ ]]; then
    echo "could not read scheduler_job_runs from the database"; return 1
  fi
  if (( age < 0 )); then echo "the scheduler has never finished a job"; return 1; fi
  if (( age >= SCHEDULER_MAX_MIN * 60 )); then
    echo "no scheduler job finished ok for $(( age / 60 )) min (limit $SCHEDULER_MAX_MIN)"; return 1
  fi
  echo "last scheduler job ok $(( age / 60 )) min ago"
}

check_backup() {
  [[ -d "$BACKUP_DIR" ]] || { echo "no backup folder $BACKUP_DIR"; return 1; }
  local fresh
  fresh="$(find "$BACKUP_DIR" -maxdepth 1 -name 'agentx-*.dump' -size +0 -mmin -$(( MAX_BACKUP_AGE_H * 60 )) 2>/dev/null | head -n 1)"
  [[ -n "$fresh" ]] && { echo "newest backup $(basename "$fresh") is under $MAX_BACKUP_AGE_H h old"; return 0; }
  if find "$BACKUP_DIR" -maxdepth 1 -name 'agentx-*.dump' 2>/dev/null | grep -q .; then
    echo "no backup newer than $MAX_BACKUP_AGE_H h in $BACKUP_DIR (nightly backup not running?)"
  else
    echo "no agentx-*.dump in $BACKUP_DIR"
  fi
  return 1
}

check_restore() {
  local f="$BACKUP_DIR/restore-test.status" line
  [[ -f "$f" ]] || { echo "restore test has not run yet"; return 0; }
  line="$(clean < "$f")"
  case "$line" in
    "ok "*) ;;
    *) echo "restore test failed: ${line#fail }"; return 1 ;;
  esac
  if [[ -z "$(find "$f" -mmin -$(( MAX_BACKUP_AGE_H * 60 )) 2>/dev/null)" ]]; then
    echo "restore test has not run for over $MAX_BACKUP_AGE_H h"; return 1
  fi
  echo "restore test: ${line#ok }"
}

check_disk() {
  local pct
  pct="$(df -P "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $5}' | clean)"
  [[ "$pct" =~ ^[0-9]+$ ]] || { echo "could not read disk use of $BACKUP_DIR"; return 1; }
  (( pct < DISK_MAX_PCT )) && { echo "disk ${pct}% used"; return 0; }
  echo "disk ${pct}% used (limit ${DISK_MAX_PCT}%)"; return 1
}

json_escape() { local s="${1//\\/\\\\}"; s="${s//\"/\\\"}"; printf '%s' "$s"; }

send() {  # send TITLE TEXT -> 0 if delivered somewhere (or nowhere is configured), 1 if all failed
  local title="$1" text="$2" ntfy slack tried=0 ok=0
  ntfy="$(env_value "$ALERTS_ENV" NTFY_URL)"
  slack="$(env_value "$ALERTS_ENV" SLACK_WEBHOOK_URL)"
  if [[ -n "$ntfy" ]]; then
    tried=1
    if curl -sS -o /dev/null --fail --max-time 15 -H "Title: $title" -H "Tags: robot" \
         --data-binary "$text" "$ntfy" 2>/dev/null; then ok=1; else log "could not reach ntfy"; fi
  fi
  if [[ -n "$slack" ]]; then
    tried=1
    if curl -sS -o /dev/null --fail --max-time 15 -H 'Content-Type: application/json' \
         --data-binary "{\"text\":\"$(json_escape "$title: $text")\"}" "$slack" 2>/dev/null; then
      ok=1
    else
      log "could not reach Slack"
    fi
  fi
  (( tried == 0 )) && log "no NTFY_URL or SLACK_WEBHOOK_URL in $ALERTS_ENV: log only"
  (( tried == 0 || ok == 1 ))
}

previous_state() { awk -v n="$1" '$1 == n {print $2}' "$STATE_FILE" 2>/dev/null | tail -n 1; }

main() {
  local name detail state prev any_bad=0 new_state=""
  mkdir -p "$(dirname "$STATE_FILE")"
  for name in $CHECKS; do
    if ! declare -F "check_$name" >/dev/null; then log "unknown check $name"; any_bad=1; continue; fi
    if detail="$("check_$name")"; then state=ok; else state=bad; any_bad=1; fi
    prev="$(previous_state "$name")"
    prev="${prev:-ok}"   # first run: only a bad check is news
    log "$name $state: $detail"
    if [[ "$state" != "$prev" ]]; then
      if [[ "$state" == bad ]]; then
        send "AgentX ALERT ($HOST_LABEL): $name" "$detail" || state="$prev"
      else
        send "AgentX OK ($HOST_LABEL): $name recovered" "$detail" || state="$prev"
      fi
    fi
    new_state+="$name $state"$'\n'
  done
  printf '%s' "$new_state" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  return "$any_bad"
}

main "$@"
