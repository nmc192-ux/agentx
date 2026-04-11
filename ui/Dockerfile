# AgentX UI — Dockerfile
# Multi-stage build: deps → builder → runtime
# Uses Next.js standalone output for a lean final image (~200 MB vs ~1 GB).
#
# Build args (baked in at image build time):
#   NEXT_PUBLIC_API_URL   HTTP base URL of the platform API
#   NEXT_PUBLIC_WS_URL    WebSocket URL for the live feed
#
# ── Stage 1: Install dependencies ─────────────────────────────────────────────
FROM node:20-alpine AS deps

WORKDIR /app

# Copy lockfile first for better layer caching
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# ── Stage 2: Build the Next.js application ────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Public env vars must be available at build time so Next.js can inline them.
# They are re-set at runtime via docker-compose environment: for the actual values.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

# ── Stage 3: Runtime image ─────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser  --system --uid 1001 nextjs

# Copy standalone build output (requires output: 'standalone' in next.config.ts)
COPY --from=builder /app/public                           ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone  ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static      ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME=0.0.0.0

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000', r => process.exit(r.statusCode === 200 ? 0 : 1))"

# server.js is emitted by `next build` when output: 'standalone' is set
CMD ["node", "server.js"]
