#!/usr/bin/env bash
# Roll a new AgentX image onto the VPS: migrate first, then api-1, then api-2 (plan §6).
# Sprint 16 (files only). The deploy workflow pipes this file over SSH; DrJ can also run it
# on the VPS by hand, which is also how a rollback is done (plan §8):
#
#   cd /opt/agentx && bash deploy.sh <40-character commit>
#   cd /opt/agentx && SKIP_MIGRATE=1 bash deploy.sh <previous commit>   # rollback
#
# A rollback skips the migration: older code's `alembic upgrade head` does not know the newer
# revision already in the database and would fail. A bad migration is undone from the Neon
# snapshot instead (plan §8).
#
# An empty database is never migrated: the bootstrap (scripts/bootstrap_db.py, EL-1) builds it
# once with the founders' production addresses, and deploy.sh refuses until it has.
#
# Order is the safety property: if the migration fails, nothing is replaced and the running
# version keeps serving. Each API container must report "healthy" before the next one is
# replaced, so Caddy always has one to send traffic to. The scheduler is restarted only if it
# was already running, never started here (exactly one scheduler, plan §5).
#
# Before anything else it makes sure of the proxy network (H29 answer, cycle 227): a small
# network shared only by Pink Popcorn's Caddy and AgentX (PROXY_NETWORK, normally agentx_edge),
# so Pink Popcorn's own app cannot reach the API directly or send it a forwarded address the
# API would believe. It creates the network if missing, (re)connects Caddy (a recreated Caddy
# container loses the connection), and refuses to deploy if the network's range is not
# PROXY_SUBNET (the API trusts forwarded headers from that range only) or anything other than
# Caddy and AgentX's own containers is on it.
#
# A successful deploy leaves $AGENTX_STATUS_DIR/deploy.json (commit, previous, time, migrated)
# for the founder BRUNO (TF-3); the scheduler reads it read-only and says nothing when it is
# missing, a week old or for another commit.
set -euo pipefail

TAG="${1:-}"
if [[ ! "$TAG" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: deploy.sh <40-character lowercase git commit>" >&2
  exit 2
fi

cd "${AGENTX_DIR:-/opt/agentx}"
[[ -f compose.env ]] || { echo "compose.env missing in $(pwd)" >&2; exit 2; }

PROJECT=agentx
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
PREVIOUS="$(sed -n 's/^IMAGE_TAG=//p' compose.env | tail -n 1)"

# Shell environment wins over --env-file, so every compose call below uses the new tag.
export IMAGE_TAG="$TAG"
dc() { docker compose --env-file compose.env "$@"; }
# A compose.env value; the shell environment wins, as it does for docker compose.
setting() { local v="${!1:-}"; [[ -n "$v" ]] || v="$(sed -n "s/^$1=//p" compose.env | tail -n 1)"; printf '%s' "$v"; }
STATUS_DIR="$(setting AGENTX_STATUS_DIR)"
STATUS_DIR="${STATUS_DIR:-/opt/agentx/status}"

# status_record NAME JSON: a small record for the founders BRUNO and QUINN (TF-3), written whole
# then renamed (never half a file) and readable by the scheduler, which mounts $STATUS_DIR
# read-only. Best effort: a record that cannot be written never fails the run.
status_record() {
  (umask 022 && mkdir -p "$STATUS_DIR" && printf '%s\n' "$2" > "$STATUS_DIR/.$1.json.tmp" \
    && chmod 644 "$STATUS_DIR/.$1.json.tmp" && mv -f "$STATUS_DIR/.$1.json.tmp" "$STATUS_DIR/$1.json") 2>/dev/null \
    || echo "warning: could not write $STATUS_DIR/$1.json" >&2
}

ensure_proxy_network() {
  local net subnet caddy caddy_id members id project
  net="$(setting PROXY_NETWORK)"
  subnet="$(setting PROXY_SUBNET)"
  caddy="$(setting CADDY_CONTAINER)"
  if [[ -z "$net" || -z "$subnet" || -z "$caddy" ]]; then
    echo "compose.env must set PROXY_NETWORK, PROXY_SUBNET and CADDY_CONTAINER" >&2
    return 2
  fi
  if ! docker network inspect "$net" >/dev/null 2>&1; then
    echo "creating network $net ($subnet)"
    docker network create --driver bridge --subnet "$subnet" "$net" >/dev/null
  fi
  if [[ "$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$net")" != "$subnet " ]]; then
    echo "refusing to deploy: network $net is not exactly $subnet (PROXY_SUBNET)" >&2
    return 1
  fi
  caddy_id="$(docker inspect -f '{{.Id}}' "$caddy" 2>/dev/null)" || {
    echo "refusing to deploy: Caddy container $caddy not found (CADDY_CONTAINER)" >&2
    return 1
  }
  # shellcheck disable=SC2016  # a Go template for docker, not a shell variable
  members="$(docker network inspect -f '{{range $id, $c := .Containers}}{{$id}} {{end}}' "$net")"
  if [[ " $members " != *" $caddy_id "* ]]; then
    echo "connecting $caddy to $net"
    docker network connect "$net" "$caddy"
  fi
  for id in $members; do
    [[ "$id" == "$caddy_id" ]] && continue
    project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$id" 2>/dev/null || true)"
    if [[ "$project" != "$PROJECT" ]]; then
      echo "refusing to deploy: container $id on $net is neither Caddy nor AgentX" >&2
      return 1
    fi
  done
}

scheduler_running() {
  [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=scheduler" --filter status=running)" ]]
}

wait_healthy() {
  local svc="$1" id status waited=0
  id="$(dc ps -q "$svc")"
  [[ -n "$id" ]] || { echo "$svc: no container" >&2; return 1; }
  while (( waited < HEALTH_TIMEOUT )); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo missing)"
    case "$status" in
      healthy) echo "$svc healthy after ${waited}s"; return 0 ;;
      unhealthy|missing) break ;;
    esac
    sleep 3
    waited=$(( waited + 3 ))
  done
  echo "$svc did not become healthy (last status: ${status:-unknown})" >&2
  dc logs --tail 50 "$svc" >&2 || true
  return 1
}

ensure_proxy_network
# Made here, as deploy, before any container mounts it (docker would make it root-owned).
(umask 022 && mkdir -p "$STATUS_DIR") || echo "warning: could not create $STATUS_DIR" >&2
echo "deploying $TAG (previous: ${PREVIOUS:-none})"
had_scheduler=no
if scheduler_running; then had_scheduler=yes; fi

dc pull api-1
if [[ "${SKIP_MIGRATE:-0}" == 1 ]]; then
  echo "skipping migration (rollback)"
else
  # EL-1: alembic cannot build an empty database (the base schema and founders come from
  # init-db.sql); it would half-build it and the bootstrap would then refuse. The check changes
  # nothing: exit 0 = AgentX baseline present, 3 = empty, anything else = stop and look.
  if ! dc --profile migrate run --rm migrate python scripts/bootstrap_db.py --check; then
    echo "refusing to migrate: the database is empty or not an AgentX database. For a new one run" >&2
    echo "  docker compose --env-file compose.env --profile migrate run --rm migrate python scripts/bootstrap_db.py" >&2
    echo "then deploy again. Nothing was replaced." >&2
    exit 1
  fi
  dc --profile migrate run --rm migrate
fi

for svc in api-1 api-2; do
  dc up -d --no-deps "$svc"
  wait_healthy "$svc"
done

if [[ "$had_scheduler" == yes ]]; then
  dc --profile scheduler up -d --no-deps scheduler
fi

# Record the running tag so a plain `docker compose up` later does not go back in time.
sed -i.bak "s/^IMAGE_TAG=.*/IMAGE_TAG=$TAG/" compose.env && rm -f compose.env.bak
migrated=true
if [[ "${SKIP_MIGRATE:-0}" == 1 ]]; then migrated=false; fi
status_record deploy "$(printf '{"commit": "%s", "previous": "%s", "finished_at": "%s", "migrated": %s}' \
  "$TAG" "${PREVIOUS:-none}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$migrated")"
echo "previous=${PREVIOUS:-none}"
echo "deployed=$TAG scheduler=$had_scheduler"
