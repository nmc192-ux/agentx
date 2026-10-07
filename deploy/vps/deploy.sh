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
# Order is the safety property: if the migration fails, nothing is replaced and the running
# version keeps serving. Each API container must report "healthy" before the next one is
# replaced, so Caddy always has one to send traffic to. The scheduler is restarted only if it
# was already running, never started here (exactly one scheduler, plan §5).
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

echo "deploying $TAG (previous: ${PREVIOUS:-none})"
had_scheduler=no
if scheduler_running; then had_scheduler=yes; fi

dc pull api-1
if [[ "${SKIP_MIGRATE:-0}" == 1 ]]; then
  echo "skipping migration (rollback)"
else
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
echo "previous=${PREVIOUS:-none}"
echo "deployed=$TAG scheduler=$had_scheduler"
