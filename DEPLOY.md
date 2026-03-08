# AgentX — Deployment Guide
## Fly.io (backend) + Vercel (frontend)

**Stack deployed:**
- FastAPI + WebSockets → **Fly.io** (`agentx-platform.fly.dev`)
- PostgreSQL 16 + pgvector → **Fly Managed Postgres**
- Redis (cache + rate limiter) → **Upstash** (serverless, TLS)
- Next.js 15 → **Vercel**

**Estimated time:** ~45 minutes first deploy; ~3 minutes subsequent deploys.

---

## Prerequisites

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Install Vercel CLI
npm i -g vercel

# Authenticate both
fly auth login
vercel login
```

You'll need accounts at [fly.io](https://fly.io) and [vercel.com](https://vercel.com).
Both have free tiers that cover this stack.

---

## Part 1 — Backend (Fly.io)

### Step 1 — Create the Fly app

```bash
cd /Users/drj/AgentX/platform

# Create the app (don't deploy yet)
fly apps create agentx-platform

# If "agentx-platform" is taken, choose a different name and update fly.toml:
#   app = "your-chosen-name"
```

### Step 2 — Provision Fly Postgres

```bash
# Creates a managed Postgres 16 cluster (free tier = 256MB)
fly postgres create \
  --name agentx-db \
  --region iad \
  --initial-cluster-size 1 \
  --vm-size shared-cpu-1x \
  --volume-size 1

# ↑ Save the output — it shows the password. You won't see it again.
#   Example output line: "Password: AbCdEfGh1234..."

# Attach to your app (sets POSTGRES_HOST automatically in fly.toml's private network)
fly postgres attach agentx-db --app agentx-platform
```

After `attach`, Fly sets `DATABASE_URL` as a secret. Our app uses individual vars instead,
so set them manually:

```bash
# Replace <password> with the password from `fly postgres create` output
fly secrets set \
  POSTGRES_HOST="agentx-db.internal" \
  POSTGRES_PASSWORD="<password from create output>" \
  --app agentx-platform
```

### Step 3 — Provision Upstash Redis

1. Go to [console.upstash.com](https://console.upstash.com) → **Create Database**
2. Name: `agentx-cache` | Region: `US-East-1` | Type: **Regional** | TLS: **On**
3. From the database page, copy:
   - **Endpoint** (hostname, e.g. `us1-xxx.upstash.io`)
   - **Password** (the long token under "REST API")

```bash
fly secrets set \
  REDIS_HOST="<endpoint from Upstash>" \
  REDIS_PASSWORD="<password from Upstash>" \
  --app agentx-platform
```

### Step 4 — Set remaining secrets

```bash
# Generate a strong JWT secret
JWT_SECRET=$(openssl rand -hex 64)

fly secrets set \
  JWT_SECRET="$JWT_SECRET" \
  --app agentx-platform

# Confirm all secrets are set
fly secrets list --app agentx-platform
# Should show: POSTGRES_HOST, POSTGRES_PASSWORD, REDIS_HOST, REDIS_PASSWORD, JWT_SECRET
```

### Step 5 — Run database migrations

The Alembic migrations need to run once against the production DB before first deploy.

```bash
# Open a temporary machine on Fly with your app's environment
fly ssh console --app agentx-platform --command "python -m alembic upgrade head"

# If the above fails (machine not yet deployed), run locally pointing at Fly DB:
# First, open a proxy tunnel to Fly Postgres:
fly proxy 5433:5432 --app agentx-db &

# Then run migrations locally via the tunnel:
cd /Users/drj/AgentX/platform
POSTGRES_HOST=localhost \
POSTGRES_PORT=5433 \
POSTGRES_USER=agentx \
POSTGRES_DB=agentx \
POSTGRES_PASSWORD="<password>" \
POSTGRES_SSL_MODE=disable \
POSTGRES_PASSWORD_FILE="" \
REDIS_PASSWORD="skip" \
REDIS_PASSWORD_FILE="" \
JWT_SECRET="skip" \
JWT_SECRET_FILE="" \
python -m alembic upgrade head

kill %1   # stop the proxy
```

### Step 6 — Deploy the backend

```bash
cd /Users/drj/AgentX/platform

fly deploy --app agentx-platform
```

Watch the build logs. A successful deploy ends with:
```
✓ Machine e286500c3d3789 [app] update succeeded
```

Verify it's live:
```bash
curl https://agentx-platform.fly.dev/health
# → {"status":"ok","version":"1.0.0","env":"production"}

curl https://agentx-platform.fly.dev/health/ready
# → {"status":"ok","dependencies":{"database":{"status":"ok"},"cache":{"status":"ok"}}}
```

---

## Part 2 — Frontend (Vercel)

### Step 7 — Deploy the frontend

```bash
cd /Users/drj/AgentX/frontend

vercel deploy --prod
```

Follow the prompts:
- **Project name:** `agentx-frontend` (or your preferred name)
- **Framework:** Next.js (auto-detected)
- **Root directory:** `.` (current directory)

After deploy, Vercel shows your URL, e.g. `https://agentx-frontend.vercel.app`.

### Step 8 — Set Vercel environment variables

In the **Vercel dashboard** (or via CLI), add these environment variables for **Production**:

```bash
vercel env add NEXT_PUBLIC_API_URL production
# Enter: https://agentx-platform.fly.dev

vercel env add NEXT_PUBLIC_WS_URL production
# Enter: wss://agentx-platform.fly.dev/ws

vercel env add NEXTAUTH_URL production
# Enter: https://agentx-frontend.vercel.app   ← your actual Vercel domain

vercel env add NEXTAUTH_SECRET production
# Enter: (generate with: openssl rand -base64 32)
```

Then redeploy to pick up the new env vars:
```bash
vercel deploy --prod
```

### Step 9 — Update CORS on the backend

Now that you know the Vercel domain, update the backend's CORS allowlist:

```bash
fly secrets set \
  CORS_ORIGINS='["https://agentx-frontend.vercel.app"]' \
  --app agentx-platform

# Fly automatically redeploys when secrets change
```

---

## Part 3 — Verification

Run this checklist after both services are deployed:

```bash
BACKEND="https://agentx-platform.fly.dev"
FRONTEND="https://agentx-frontend.vercel.app"

# 1. Backend liveness
curl -s $BACKEND/health | jq .
# Expect: {"status":"ok"}

# 2. Backend readiness (DB + Redis connected)
curl -s $BACKEND/health/ready | jq .
# Expect: {"status":"ok","dependencies":{"database":{"status":"ok"},"cache":{"status":"ok"}}}

# 3. CORS headers (from Vercel domain)
curl -s -H "Origin: $FRONTEND" -I $BACKEND/health | grep -i "access-control"
# Expect: access-control-allow-origin: https://agentx-frontend.vercel.app

# 4. Frontend loads
curl -s -o /dev/null -w "%{http_code}" $FRONTEND
# Expect: 200

# 5. WebSocket (requires wscat: npm i -g wscat)
wscat -c "wss://agentx-platform.fly.dev/ws"
# Expect: Connected (press Ctrl+C to exit)
```

---

## Subsequent Deploys

After the initial setup, deploying changes is just:

```bash
# Backend
cd /Users/drj/AgentX/platform && fly deploy

# Frontend (auto-deploys on git push if connected to GitHub, or manually:)
cd /Users/drj/AgentX/frontend && vercel deploy --prod
```

---

## Monitoring & Logs

```bash
# Live backend logs
fly logs --app agentx-platform

# Backend machine status
fly status --app agentx-platform

# Scale up (e.g. before a load test)
fly scale count 2 --app agentx-platform
fly scale count 1 --app agentx-platform   # scale back down
```

Vercel logs are available in the Vercel dashboard under **Deployments → Functions**.

---

## Cost Breakdown

| Service | Tier | Monthly Cost |
|---------|------|-------------|
| Fly.io (1× shared-cpu-2x, 512MB) | Pay-as-you-go | ~$7/mo |
| Fly Postgres (1GB, shared-cpu-1x) | Pay-as-you-go | ~$7/mo |
| Upstash Redis (10K req/day free) | Free → $10/mo | $0–10/mo |
| Vercel | Hobby (free) | $0/mo |
| **Total** | | **~$14–24/mo** |

---

## Scaling Up

When you need more capacity:

```bash
# More backend machines (horizontal scale)
fly scale count 2 --app agentx-platform

# Bigger machines (vertical scale)
fly scale vm performance-1x --app agentx-platform   # dedicated vCPU

# Postgres replicas (read scaling)
fly postgres update agentx-db --initial-cluster-size 2
```

**Migration path to AWS:** The backend runs in Docker, so migration to ECS is:
1. Push the same `Dockerfile` to ECR
2. Point ECS task to RDS (PostgreSQL) + ElastiCache (Redis)
3. Update env vars — no code changes needed.

---

## Security Notes

- `/docs` and `/redoc` are **disabled** in production (`APP_ENV=production`)
- `client_credentials` grant is **blocked** in production (MARCUS hardening)
- All secrets are stored in Fly's encrypted secret store — never in `fly.toml`
- WebSocket connections (`/ws`) require a valid JWT bearer token
- CORS is locked to your specific Vercel domain (no wildcards)
