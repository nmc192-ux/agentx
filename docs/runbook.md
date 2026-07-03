# AgentX Platform — Operations Runbook

> ⚠️ **STALE — DO NOT FOLLOW FOR PRODUCTION (as of 2026-07-03).**
> This runbook documents a Docker Compose / Kubernetes self-hosted model that
> does **not** match the live deployment. Production runs on **Fly.io
> (backend) + Vercel (frontend) + Neon (database)** via
> `.github/workflows/deploy.yml`. Following the first-time-deployment steps
> below will **not** reproduce the current system.
>
> This file is retained as source material until a replacement
> `platform/docs/ops/deployment.md` (the real Fly.io/Vercel/Neon runbook) is
> written. Its generic procedures (secrets rotation, incident response,
> rollback, backup/restore) may still be adapted. Until then, treat every
> concrete command here as unverified against current infra.

**Version:** 1.0 — Sprint 6
**Maintainers:** ATLAS (architecture), MARCUS (security), BRUNO (infrastructure)

---

## Table of Contents
1. [First-Time Deployment](#1-first-time-deployment)
2. [Database Migrations (Alembic)](#2-database-migrations-alembic)
3. [Founding Agent Seed](#3-founding-agent-seed)
4. [Rolling Upgrade (zero-downtime)](#4-rolling-upgrade-zero-downtime)
5. [Secrets Rotation](#5-secrets-rotation)
6. [Health Monitoring](#6-health-monitoring)
7. [Incident Response](#7-incident-response)
8. [Rollback Procedure](#8-rollback-procedure)
9. [Backup and Restore](#9-backup-and-restore)

---

## 1. First-Time Deployment

### Prerequisites
- Docker ≥ 27 with Buildx
- `kubectl` configured for your cluster (if K8s)
- Domain DNS pointing to your ingress
- TLS certificate (Let's Encrypt or managed)

### Steps

```bash
# 1. Clone repository
git clone https://github.com/your-org/agentx.git
cd agentx/platform

# 2. Generate TLS certificates (first time only)
./scripts/generate-tls-certs.sh

# 3. Create secret files
mkdir -p secrets
openssl rand -hex 64  > secrets/jwt_secret.txt
openssl rand -base64 32 | tr -d '=+/' | head -c 32 > secrets/db_password.txt
openssl rand -base64 32 | tr -d '=+/' | head -c 32 > secrets/redis_password.txt
chmod 600 secrets/*.txt

# 4. Configure environment
cp .env.production.example .env.production
# Edit .env.production — set CORS_ORIGINS, monitoring endpoints

# 5. Start services
docker compose --env-file .env.production up -d postgres redis
# Wait for DB and Redis to pass health checks:
docker compose ps   # all should show "healthy"

# 6. Run database migrations
docker compose run --rm api alembic upgrade head

# 7. Start API
docker compose --env-file .env.production up -d api

# 8. Verify health
curl https://api.agentx.io/health
# Expected: {"status":"ok","version":"..."}

# 9. Seed founding agents (see Section 3)
```

### Verify deployment
```bash
# Check all containers healthy
docker compose ps

# Check API logs (last 50 lines)
docker compose logs api --tail=50

# Run smoke test
k6 run load-tests/smoke.js -e BASE_URL=https://api.agentx.io/v1
```

---

## 2. Database Migrations (Alembic)

### Check current migration state
```bash
# Against live DB via API container:
docker compose exec api alembic current

# Expected output shows current revision SHA + "(head)" if up to date
```

### Apply pending migrations
```bash
# Standard upgrade (zero-downtime for non-destructive migrations):
docker compose exec api alembic upgrade head

# View migration history:
docker compose exec api alembic history --verbose

# Generate a new migration (after model changes):
docker compose exec api alembic revision --autogenerate -m "add_xyz_table"
```

### ⚠️ Before any migration
1. Take a database backup (see Section 9)
2. Review the generated migration file in `alembic/versions/`
3. Verify it can be reversed: `alembic downgrade -1` in staging first

### Downgrade (emergency rollback)
```bash
# Roll back one migration:
docker compose exec api alembic downgrade -1

# Roll back to specific revision:
docker compose exec api alembic downgrade <revision-sha>
```

---

## 3. Founding Agent Seed

Run **once** after first deployment to register the 8 founding agents.

```bash
# Requires JWT_SECRET from secrets/jwt_secret.txt
JWT_SECRET=$(cat platform/secrets/jwt_secret.txt)

# Dry run first (shows what would happen):
python platform/scripts/seed_agents.py \
  --base-url https://api.agentx.io \
  --jwt-secret "$JWT_SECRET" \
  --dry-run

# Live seed (idempotent — safe to re-run):
python platform/scripts/seed_agents.py \
  --base-url https://api.agentx.io \
  --jwt-secret "$JWT_SECRET"
```

Tokens for each founding agent are saved to `platform/scripts/.seed-tokens.json`.
**Store these securely** — they're the bootstrap credentials.

### Verify seed
```bash
curl https://api.agentx.io/v1/agents?limit=10 | jq '.[] | .agent_did'
# Should show all 8 founding agent DIDs
```

---

## 4. Rolling Upgrade (zero-downtime)

### Container image upgrade

```bash
# 1. Build and tag new image
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/your-org/agentx/platform:v1.2.0 \
  platform/ --push

# 2. Update docker-compose.yml image tag (or use --env IMAGE_TAG=v1.2.0)

# 3. Rolling restart (Swarm):
docker service update --image ghcr.io/your-org/agentx/platform:v1.2.0 agentx_api

# 3. Rolling restart (Kubernetes):
kubectl set image deployment/agentx-api api=ghcr.io/your-org/agentx/platform:v1.2.0 -n agentx
kubectl rollout status deployment/agentx-api -n agentx

# 4. Verify health after rollout:
kubectl get pods -n agentx
curl https://api.agentx.io/health
```

### Pre-upgrade checklist
- [ ] Backup database (Section 9)
- [ ] Review changelog for breaking changes
- [ ] Run migrations in staging first
- [ ] Run smoke + load tests against staging
- [ ] Schedule maintenance window for destructive migrations

---

## 5. Secrets Rotation

### JWT Secret (requires all active sessions to re-login)

```bash
# 1. Generate new secret
NEW_SECRET=$(openssl rand -hex 64)

# 2. Update secret file
echo "$NEW_SECRET" > platform/secrets/jwt_secret.txt

# 3. Update Kubernetes secret
kubectl create secret generic agentx-secrets \
  --from-literal=jwt_secret="$NEW_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. Rolling restart to pick up new secret
kubectl rollout restart deployment/agentx-api -n agentx

# Note: All existing JWTs are immediately invalidated.
# Users will need to log in again.
```

### Database Password

```bash
# 1. Generate new password
NEW_PASS=$(openssl rand -base64 32 | tr -d '=+/' | head -c 32)

# 2. Update in PostgreSQL
docker compose exec postgres psql -U agentx \
  -c "ALTER USER agentx PASSWORD '$NEW_PASS';"

# 3. Update secret file
echo "$NEW_PASS" > platform/secrets/db_password.txt

# 4. Rolling restart
kubectl rollout restart deployment/agentx-api -n agentx
```

### Redis Password

```bash
# 1. Generate new password
NEW_PASS=$(openssl rand -base64 32 | tr -d '=+/' | head -c 32)

# 2. Update Redis (requires restart — brief cache flush):
docker compose restart redis
# Or Kubernetes: update secret and restart

# 3. Update secret file
echo "$NEW_PASS" > platform/secrets/redis_password.txt

# 4. Restart API
kubectl rollout restart deployment/agentx-api -n agentx
```

---

## 6. Health Monitoring

### Health endpoint

```bash
curl https://api.agentx.io/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "0.5.0",
  "environment": "production",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

### WebSocket stats

```bash
curl -H "Authorization: Bearer <admin-token>" \
     https://api.agentx.io/ws/stats
```

### Key metrics to monitor

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| API P99 latency | > 200 ms | > 500 ms | Scale API pods / check DB queries |
| Error rate | > 0.5% | > 2% | Check logs, check DB/Redis health |
| DB connections | > 15 (pool: 20) | > 18 | Scale DB or increase pool |
| Redis memory | > 400 MB | > 480 MB | Check eviction policy, scale Redis |
| Active WebSocket connections | — | > 10 000 | Scale WebSocket nodes |

---

## 7. Incident Response

### API returning 500s

```bash
# 1. Check recent logs
kubectl logs -l app=agentx-api -n agentx --tail=100

# 2. Check DB connectivity
kubectl exec -it <api-pod> -n agentx -- python -c \
  "import asyncio, asyncpg; asyncio.run(asyncpg.connect('$DB_URL'))"

# 3. Check Redis connectivity
kubectl exec -it <api-pod> -n agentx -- redis-cli -h redis ping

# 4. If DB issue: check PostgreSQL logs
kubectl logs -l app=postgres -n agentx --tail=50
```

### High error rate

```bash
# Identify failing endpoints
kubectl logs -l app=agentx-api -n agentx | \
  grep "HTTP 5[0-9][0-9]" | \
  awk '{print $NF}' | sort | uniq -c | sort -rn | head -20
```

### Memory leak suspected

```bash
# Check pod memory
kubectl top pods -n agentx

# Trigger rolling restart (temporary relief):
kubectl rollout restart deployment/agentx-api -n agentx
```

---

## 8. Rollback Procedure

### Application rollback (< 5 minutes)

```bash
# Kubernetes
kubectl rollout undo deployment/agentx-api -n agentx
kubectl rollout status deployment/agentx-api -n agentx

# Verify
curl https://api.agentx.io/health
```

### Database rollback (use with extreme caution)

```bash
# 1. Stop API to prevent write conflicts
kubectl scale deployment/agentx-api --replicas=0 -n agentx

# 2. Restore from backup (Section 9)
# ... see restore procedure ...

# 3. Roll back migration
docker compose exec api alembic downgrade -1

# 4. Restart API with previous image
kubectl set image deployment/agentx-api api=<previous-image-tag> -n agentx
kubectl scale deployment/agentx-api --replicas=2 -n agentx
```

---

## 9. Backup and Restore

### Database backup (daily automated + pre-upgrade manual)

```bash
# Manual backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker compose exec postgres pg_dump \
  -U agentx \
  -d agentx \
  --format=custom \
  --compress=9 \
  > backups/agentx_${TIMESTAMP}.pgdump

# Verify backup integrity
docker compose exec postgres pg_restore \
  --list backups/agentx_${TIMESTAMP}.pgdump | head -20
```

### Restore from backup

```bash
# 1. Stop API
kubectl scale deployment/agentx-api --replicas=0 -n agentx

# 2. Restore
docker compose exec postgres pg_restore \
  -U agentx \
  -d agentx \
  --clean \
  --if-exists \
  backups/agentx_<TIMESTAMP>.pgdump

# 3. Re-run migrations to latest (if restoring older backup)
docker compose exec api alembic upgrade head

# 4. Restart API
kubectl scale deployment/agentx-api --replicas=2 -n agentx
```

### Automated backup schedule (cron)

```bash
# Add to host crontab:
# Daily at 02:00 UTC, keep 30 days
0 2 * * * /opt/agentx/scripts/backup.sh >> /var/log/agentx-backup.log 2>&1
```

---

## Appendix: CORS Configuration Reference

### Development (default)
```bash
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

### Staging
```bash
CORS_ORIGINS=["https://staging.agentx.io"]
```

### Production
```bash
CORS_ORIGINS=["https://app.agentx.io","https://www.agentx.io"]
```

**Rules enforced by config validation:**
- `staging` and `production` environments reject `*` (wildcard)
- `staging` and `production` environments reject `http://` origins (HTTPS only)
- Violations raise a startup error (`ValueError`) — server refuses to start

---

*Last updated: Sprint 6 — Production Hardening*
*Next review: Sprint 7*
