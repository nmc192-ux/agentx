#!/bin/bash
#
# AgentX — Bootstrap Staging Secrets
# ══════════════════════════════════
# One-shot script to generate random secrets and print the fly CLI commands
# needed to configure agentx-staging.
#
# Usage:
#   bash scripts/bootstrap-staging.sh
#
# Then copy-paste the printed commands into your terminal.

set -e

echo "Generating secure random secrets…"
echo ""

JWT_SECRET=$(openssl rand -hex 32)
SECRET_KEY=$(openssl rand -hex 32)

echo "════════════════════════════════════════════════════════════════════════"
echo "Copy and paste these commands into your terminal:"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "fly secrets set -a agentx-staging JWT_SECRET_KEY='$JWT_SECRET'"
echo "fly secrets set -a agentx-staging SECRET_KEY='$SECRET_KEY'"
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "Then verify they were set:"
echo "  fly secrets list --app agentx-staging"
echo ""
