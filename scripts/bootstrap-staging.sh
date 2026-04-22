#!/bin/bash
#
# AgentX — Bootstrap Staging Secrets
# ══════════════════════════════════
# One-shot script to print the fly CLI commands needed to set all required
# secrets on agentx-platform-staging.
#
# Usage:
#   bash scripts/bootstrap-staging.sh
#
# Then copy-paste the printed commands into your terminal.
# Secrets with <<SET_MANUALLY>> must be filled in by hand (from your provider).

set -e

JWT_SECRET=$(openssl rand -hex 32)

echo "════════════════════════════════════════════════════════════════════════"
echo " AgentX Staging — Required Fly.io Secrets"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "# 1. Generated secrets (safe to paste directly)"
echo "fly secrets set -a agentx-platform-staging \\"
echo "  JWT_SECRET='${JWT_SECRET}'"
echo ""
echo "# 2. Fetch from Neon (staging branch connection string — password only)"
echo "fly secrets set -a agentx-platform-staging \\"
echo "  POSTGRES_PASSWORD='<<NEON_STAGING_BRANCH_PASSWORD>>'"
echo ""
echo "# 3. Fetch from Upstash (agentx-cache → .env tab → UPSTASH_REDIS_REST_TOKEN)"
echo "#    Use native Redis URL: rediss://default:<TOKEN>@<HOST>:6379"
echo "fly secrets set -a agentx-platform-staging \\"
echo "  REDIS_PASSWORD='<<UPSTASH_TOKEN_VALUE>>'"
echo ""
echo "# 4. Sentry DSN — from sentry.io → Settings → Projects → agentx-backend → Client Keys"
echo "fly secrets set -a agentx-platform-staging \\"
echo "  SENTRY_DSN='<<SENTRY_BACKEND_DSN>>'"
echo ""
echo "# 5. (Optional) Honeycomb tracing"
echo "# fly secrets set -a agentx-platform-staging \\"
echo "#   OTEL_EXPORTER_OTLP_ENDPOINT='https://api.honeycomb.io' \\"
echo "#   OTEL_EXPORTER_OTLP_HEADERS='x-honeycomb-team=<<HONEYCOMB_API_KEY>>'"
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "Verify after setting:"
echo "  fly secrets list --app agentx-platform-staging"
echo ""
