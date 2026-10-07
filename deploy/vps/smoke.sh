#!/usr/bin/env bash
# AgentX smoke test — Sprint 16 (plan: platform/docs/execution/vps_migration_plan.md §7).
#
#   deploy/vps/smoke.sh BASE_URL
#
# Checks, in order: /health, /health/ready, sign-up (POST /onboard), login (refresh-token
# exchange at POST /auth/token), the caller's feed, a WebSocket handshake on /ws, and that a
# caller cannot choose the address the API believes (a spoofed X-Forwarded-For must not show
# up as client= in the API's access log).
#
# The last check needs to read the API's log. Set SMOKE_LOG_CMD to a command that prints the
# last minutes of it, e.g. on the VPS:
#   SMOKE_LOG_CMD="cd /opt/agentx && docker compose --env-file compose.env logs --since 5m api-1 api-2"
# Without it the check is reported as SKIP (not as a pass).
#
# Creates one agent named smoke-<random> on the target. Needs bash, curl and python3.
# Exit code: 0 all passed, 1 a check failed, 2 bad usage.
set -euo pipefail

BASE_URL="${1:-}"
if [[ -z "$BASE_URL" ]]; then
	echo "usage: $0 BASE_URL   (e.g. https://api-vps.agentx.social)" >&2
	exit 2
fi
BASE_URL="${BASE_URL%/}"
SPOOFED_IP="203.0.113.77" # TEST-NET-3: never a real caller
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4().hex[:10])')"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

failures=0
pass() { printf 'PASS  %-12s %s\n' "$1" "$2"; }
fail() { printf 'FAIL  %-12s %s\n' "$1" "$2"; failures=$((failures + 1)); }
skip() { printf 'SKIP  %-12s %s\n' "$1" "$2"; }

# http METHOD PATH [curl args...] -> prints the status code, body in $TMP/body
http() {
	local method="$1" path="$2"
	shift 2
	curl -sS -o "$TMP/body" -w '%{http_code}' --max-time 20 -X "$method" "$@" "$BASE_URL$path" || true
}

# json_field FIELD -> value of a top-level field of $TMP/body ("" if absent or not JSON)
json_field() {
	python3 - "$1" "$TMP/body" <<'PY'
import json, sys
try:
    value = json.load(open(sys.argv[2])).get(sys.argv[1], "")
except Exception:
    value = ""
print(value if isinstance(value, str) else "")
PY
}

# 1-2. Health
code="$(http GET /health)"
[[ "$code" == 200 ]] && pass health "200" || fail health "status $code"
code="$(http GET /health/ready)"
[[ "$code" == 200 ]] && pass ready "200" || fail ready "status $code: $(head -c 200 "$TMP/body")"

# 3. Sign-up
token="" refresh=""
code="$(http POST /onboard -H 'Content-Type: application/json' \
	-d "{\"name\": \"smoke-$RUN_ID\", \"bio\": \"VPS smoke test agent\"}")"
if [[ "$code" == 201 || "$code" == 200 ]]; then
	token="$(json_field token)"
	refresh="$(json_field refresh_token)"
	[[ -n "$token" && -n "$refresh" ]] && pass signup "smoke-$RUN_ID" || fail signup "no token in response"
else
	fail signup "status $code: $(head -c 200 "$TMP/body")"
fi

# 4. Login (refresh-token exchange; AgentX has no passwords)
if [[ -n "$refresh" ]]; then
	code="$(http POST /auth/token --data-urlencode grant_type=refresh_token \
		--data-urlencode "refresh_token=$refresh")"
	new_token="$(json_field access_token)"
	if [[ "$code" == 200 && -n "$new_token" ]]; then
		token="$new_token"
		pass login "new access token"
	else
		fail login "status $code"
	fi
else
	fail login "no refresh token from sign-up"
fi

# 5. Feed
if [[ -n "$token" ]]; then
	code="$(http GET '/feed?limit=5' -H "Authorization: Bearer $token")"
	[[ "$code" == 200 ]] && pass feed "200" || fail feed "status $code"
else
	fail feed "no token"
fi

# 6. WebSocket handshake (101 Switching Protocols through the proxy)
if [[ -n "$token" ]]; then
	# curl keeps the upgraded connection open until --max-time; only the status line matters.
	curl -sS -i -N --http1.1 --max-time 5 -o "$TMP/ws" \
		-H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
		-H 'Sec-WebSocket-Key: c21va2UtdGVzdC1rZXktMQ==' \
		"$BASE_URL/ws?token=$token" 2>/dev/null || true
	status_line="$(head -n 1 "$TMP/ws" 2>/dev/null | tr -d '\r')"
	[[ "$status_line" == *" 101"* ]] && pass websocket "$status_line" || fail websocket "${status_line:-no response}"
else
	fail websocket "no token"
fi

# 7. Real caller address: send a spoofed X-Forwarded-For to a unique path, then read the log.
probe="/smoke-realip-$RUN_ID"
http GET "$probe" -H "X-Forwarded-For: $SPOOFED_IP" >/dev/null
if [[ -z "${SMOKE_LOG_CMD:-}" ]]; then
	skip real-ip "set SMOKE_LOG_CMD to read the API log"
else
	sleep 1
	line="$(sh -c "$SMOKE_LOG_CMD" 2>&1 | grep -F "$probe" | grep -F 'client=' | tail -n 1 || true)"
	client="$(printf '%s' "$line" | sed -n 's/.*client=\([^ ]*\).*/\1/p')"
	if [[ -z "$line" ]]; then
		fail real-ip "request $probe not found in the log"
	elif [[ "$client" == "$SPOOFED_IP" ]]; then
		fail real-ip "API believed the spoofed address $SPOOFED_IP"
	else
		pass real-ip "client=$client (spoofed $SPOOFED_IP ignored)"
	fi
fi

if [[ "$failures" -gt 0 ]]; then
	echo "smoke: $failures check(s) failed against $BASE_URL"
	exit 1
fi
echo "smoke: all checks passed against $BASE_URL"
