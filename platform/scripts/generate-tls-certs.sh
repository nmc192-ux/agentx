#!/usr/bin/env bash
# AgentX — TLS Certificate Generator
# MARCUS P0 Gap 2: All inter-service traffic must be encrypted
#
# Generates:
#   certs/ca.{crt,key}            — Self-signed CA (dev only)
#   certs/postgres/{server.crt,server.key,ca.crt}
#   certs/redis/{server.crt,server.key,ca.crt}
#   certs/api/{server.crt,server.key,ca.crt}
#
# Usage:
#   ./scripts/generate-tls-certs.sh
#   ./scripts/generate-tls-certs.sh --days 3650   # 10 year dev certs
#
# Production: Replace with cert-manager + Let's Encrypt or internal PKI.

set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
DAYS="${1:-365}"
COUNTRY="US"
ORG="AgentX Platform"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  🔐  AgentX TLS Certificate Generator                        ║"
echo "║  Output: $CERT_DIR"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

mkdir -p "$CERT_DIR"/{postgres,redis,api}

# ── Generate CA ────────────────────────────────────────────────────────────────
echo "→ Generating CA key and certificate..."
openssl genrsa -out "$CERT_DIR/ca.key" 4096 2>/dev/null
openssl req -new -x509 -days "$DAYS" \
  -key "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt" \
  -subj "/C=$COUNTRY/O=$ORG/CN=AgentX-CA" \
  2>/dev/null
echo "  ✓ CA: $CERT_DIR/ca.{key,crt}"

# ── Helper: generate service cert ─────────────────────────────────────────────
gen_cert() {
  local SERVICE="$1"
  local CN="$2"
  local SAN="$3"
  local OUT="$CERT_DIR/$SERVICE"

  echo "→ Generating $SERVICE certificate (CN=$CN)..."

  openssl genrsa -out "$OUT/server.key" 2048 2>/dev/null
  openssl req -new \
    -key "$OUT/server.key" \
    -out "$OUT/server.csr" \
    -subj "/C=$COUNTRY/O=$ORG/CN=$CN" \
    2>/dev/null

  # Sign with CA, including SAN extension
  openssl x509 -req -days "$DAYS" \
    -in "$OUT/server.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$OUT/server.crt" \
    -extensions v3_req \
    -extfile <(cat <<EOF
[req]
req_extensions = v3_req
[v3_req]
subjectAltName = $SAN
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
EOF
    ) 2>/dev/null

  # Copy CA cert to service directory
  cp "$CERT_DIR/ca.crt" "$OUT/ca.crt"

  # Fix permissions — private keys must not be world-readable
  chmod 600 "$OUT/server.key"
  chmod 644 "$OUT/server.crt" "$OUT/ca.crt"

  rm -f "$OUT/server.csr"
  echo "  ✓ $SERVICE: $OUT/"
}

# ── Generate service certificates ─────────────────────────────────────────────
gen_cert "postgres" "postgres"  "DNS:postgres,DNS:localhost,IP:127.0.0.1"
gen_cert "redis"    "redis"     "DNS:redis,DNS:localhost,IP:127.0.0.1"
gen_cert "api"      "agentx-api" "DNS:api,DNS:localhost,IP:127.0.0.1"

# ── Verify certificates ────────────────────────────────────────────────────────
echo ""
echo "→ Verifying certificate chain..."
for SERVICE in postgres redis api; do
  openssl verify -CAfile "$CERT_DIR/ca.crt" "$CERT_DIR/$SERVICE/server.crt" >/dev/null 2>&1 && \
    echo "  ✓ $SERVICE cert verified against CA" || \
    echo "  ✗ $SERVICE cert verification FAILED"
done

# ── Create secrets/ directory for docker-compose ──────────────────────────────
SECRETS_DIR="$(dirname "$CERT_DIR")/secrets"
mkdir -p "$SECRETS_DIR"

if [ ! -f "$SECRETS_DIR/db_password.txt" ]; then
  openssl rand -base64 32 > "$SECRETS_DIR/db_password.txt"
  echo ""
  echo "→ Generated new DB password: $SECRETS_DIR/db_password.txt"
fi

if [ ! -f "$SECRETS_DIR/redis_password.txt" ]; then
  openssl rand -base64 32 > "$SECRETS_DIR/redis_password.txt"
  echo "→ Generated new Redis password: $SECRETS_DIR/redis_password.txt"
fi

if [ ! -f "$SECRETS_DIR/jwt_secret.txt" ]; then
  openssl rand -base64 64 > "$SECRETS_DIR/jwt_secret.txt"
  echo "→ Generated new JWT secret: $SECRETS_DIR/jwt_secret.txt"
fi

chmod 600 "$SECRETS_DIR"/*.txt

# ── .gitignore guard ──────────────────────────────────────────────────────────
PLATFORM_DIR="$(dirname "$CERT_DIR")"
GITIGNORE="$PLATFORM_DIR/.gitignore"
if [ ! -f "$GITIGNORE" ] || ! grep -q "certs/" "$GITIGNORE"; then
  echo "certs/" >> "$GITIGNORE"
  echo "secrets/" >> "$GITIGNORE"
  echo ".env" >> "$GITIGNORE"
  echo "→ Added certs/, secrets/, .env to .gitignore"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅  TLS certs + secrets ready                                ║"
echo "║  Now run: docker compose up -d                               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
