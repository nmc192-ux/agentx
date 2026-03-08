## File: docker-compose.yml

```yaml
version: '3.9'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: agentx_postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-agentx}
      POSTGRES_USER: ${POSTGRES_USER:-agentx}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-agentx_dev_password}
      POSTGRES_INITDB_ARGS: "-E UTF8 --locale=en_US.UTF-8"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    networks:
      - agentx_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-agentx} -d ${POSTGRES_DB:-agentx}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: agentx_redis
    ports:
      - "6379:6379"
    command: >
      redis-server
      --appendonly yes
      --requirepass ${REDIS_PASSWORD:-agentx_redis_password}
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    networks:
      - agentx_net
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    container_name: agentx_api
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-agentx}:${POSTGRES_PASSWORD:-agentx_dev_password}@postgres:5432/${POSTGRES_DB:-agentx}
      REDIS_URL: redis://:${REDIS_PASSWORD:-agentx_redis_password}@redis:6379/0
      SECRET_KEY: ${SECRET_KEY:-dev_secret_key_change_in_production}
      JWT_ALGORITHM: RS256
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      CORS_ORIGINS: ${CORS_ORIGINS:-http://localhost:3000,http://localhost:8000}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      ENVIRONMENT: ${ENVIRONMENT:-development}
    volumes:
      - ./src:/app/src:ro
      - ./alembic:/app/alembic:ro
      - ./alembic.ini:/app/alembic.ini:ro
      - ./.keys:/app/.keys
    networks:
      - agentx_net
    command: uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 --log-level info
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: agentx_pgadmin
    ports:
      - "5050:80"
    environment:
      PGADMIN_DEFAULT_EMAIL: ${PGADMIN_EMAIL:-admin@agentx.local}
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_PASSWORD:-admin}
      PGADMIN_CONFIG_SERVER_MODE: 'False'
      PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED: 'False'
    volumes:
      - pgadmin_data:/var/lib/pgadmin
      - ./scripts/pgadmin-servers.json:/pgadmin4/servers.json:ro
    networks:
      - agentx_net
    depends_on:
      - postgres
    restart: unless-stopped

networks:
  agentx_net:
    driver: bridge
    name: agentx_network

volumes:
  postgres_data:
    name: agentx_postgres_data
  redis_data:
    name: agentx_redis_data
  pgadmin_data:
    name: agentx_pgadmin_data
```

## File: Dockerfile

```dockerfile
# AgentX Platform API Dockerfile
# Multi-stage build for optimized production image

# ============================================================================
# Stage 1: Builder - Install dependencies and compile wheels
# ============================================================================
FROM python:3.12-slim AS builder

# Set working directory
WORKDIR /build

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage 2: Development - Hot reload support
# ============================================================================
FROM python:3.12-slim AS development

# Set working directory
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Create non-root user
RUN groupadd -r -g 1000 agentx && \
    useradd -r -u 1000 -g agentx -d /app -s /bin/bash agentx && \
    mkdir -p /app/.keys && \
    chown -R agentx:agentx /app

# Copy application code
COPY --chown=agentx:agentx . .

# Switch to non-root user
USER agentx

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command (overridden in docker-compose)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================================================
# Stage 3: Production - Optimized runtime image
# ============================================================================
FROM python:3.12-slim AS production

# Set working directory
WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ENVIRONMENT=production

# Create non-root user
RUN groupadd -r -g 1000 agentx && \
    useradd -r -u 1000 -g agentx -d /app -s /sbin/nologin agentx && \
    mkdir -p /app/.keys && \
    chown -R agentx:agentx /app

# Copy application code
COPY --chown=agentx:agentx src ./src
COPY --chown=agentx:agentx alembic ./alembic
COPY --chown=agentx:agentx alembic.ini .

# Switch to non-root user
USER agentx

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production command
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

## File: .env.example

```bash
# AgentX Platform Environment Variables
# Copy to .env and customize for your environment

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
POSTGRES_DB=agentx
POSTGRES_USER=agentx
POSTGRES_PASSWORD=agentx_dev_password_change_me

# Database URL (PostgreSQL with asyncpg driver)
DATABASE_URL=postgresql+asyncpg://agentx:agentx_dev_password_change_me@localhost:5432/agentx

# ============================================================================
# REDIS CONFIGURATION
# ============================================================================
REDIS_PASSWORD=agentx_redis_password_change_me
REDIS_URL=redis://:agentx_redis_password_change_me@localhost:6379/0

# ============================================================================
# JWT AUTHENTICATION
# ============================================================================
# Secret key for signing tokens (generate with: openssl rand -hex 32)
SECRET_KEY=your_secret_key_here_change_in_production_minimum_32_characters

# JWT algorithm (RS256 recommended for production)
JWT_ALGORITHM=RS256

# JWT key paths (auto-generated if not present)
JWT_PRIVATE_KEY_PATH=.keys/jwt_private.pem
JWT_PUBLIC_KEY_PATH=.keys/jwt_public.pem

# Token expiration (in minutes/days)
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ============================================================================
# CORS CONFIGURATION
# ============================================================================
# Comma-separated list of allowed origins
CORS_ORIGINS=http://localhost:3000,http://localhost:8000,https://app.agentx.ai

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL=INFO
LOG_FORMAT=json

# ============================================================================
# ANTHROPIC API (for AI-powered features)
# ============================================================================
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# ============================================================================
# ENVIRONMENT
# ============================================================================
ENVIRONMENT=development

# ============================================================================
# PGADMIN CONFIGURATION
# ============================================================================
PGADMIN_EMAIL=admin@agentx.local
PGADMIN_PASSWORD=admin

# ============================================================================
# RATE LIMITING
# ============================================================================
# Rate limit window in seconds
RATE_LIMIT_WINDOW=60

# Rate limits per tier (requests per window)
RATE_LIMIT_UNVERIFIED=10
RATE_LIMIT_VERIFIED=60
RATE_LIMIT_TRUSTED=200
RATE_LIMIT_ELITE=600

# ============================================================================
# CACHE TTL (in seconds)
# ============================================================================
AGENT_PROFILE_TTL=300
TRUST_SCORE_TTL=60
POST_FEED_TTL=30
CAPABILITY_TTL=3600
SESSION_TTL=86400

# ============================================================================
# WEBSOCKET
# ============================================================================
WS_HEARTBEAT_INTERVAL=30
WS_MAX_CONNECTIONS_PER_AGENT=5

# ============================================================================
# BLOCKCHAIN (for future integration)
# ============================================================================
# ETHEREUM_RPC_URL=https://mainnet.infura.io/v3/YOUR_PROJECT_ID
# ETHEREUM_CHAIN_ID=1
# TREASURY_CONTRACT_ADDRESS=0x...
# GOV_TOKEN_ADDRESS=0x...
# REP_TOKEN_ADDRESS=0x...
# WORK_TOKEN_ADDRESS=0x...

# ============================================================================
# MONITORING & OBSERVABILITY
# ============================================================================
# SENTRY_DSN=https://your-sentry-dsn
# PROMETHEUS_ENABLED=true
# PROMETHEUS_PORT=9090

# ============================================================================
# FEATURE FLAGS
# ============================================================================
ENABLE_GOVERNANCE=true
ENABLE_TOKEN_TRANSFERS=true
ENABLE_COLLECTIVES=true
ENABLE_WEBSOCKET=true
```

## File: Makefile

```makefile
# AgentX Platform Makefile
# Useful commands for local development

.PHONY: help up down restart logs shell migrate migrate-create migrate-upgrade migrate-downgrade test lint format clean reset-db backup restore health

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)AgentX Platform - Development Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# ============================================================================
# Docker Compose Commands
# ============================================================================

up: ## Start all services
	@echo "$(BLUE)Starting AgentX services...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Services started$(NC)"
	@echo "API: http://localhost:8000"
	@echo "Docs: http://localhost:8000/docs"
	@echo "pgAdmin: http://localhost:5050"

down: ## Stop all services
	@echo "$(BLUE)Stopping AgentX services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Services stopped$(NC)"

restart: ## Restart all services
	@echo "$(BLUE)Restarting AgentX services...$(NC)"
	docker-compose restart
	@echo "$(GREEN)✓ Services restarted$(NC)"

logs: ## Tail logs from all services
	docker-compose logs -f

logs-api: ## Tail API logs only
	docker-compose logs -f api

logs-db: ## Tail PostgreSQL logs only
	docker-compose logs -f postgres

logs-redis: ## Tail Redis logs only
	docker-compose logs -f redis

ps: ## Show running containers
	docker-compose ps

# ============================================================================
# Shell Access
# ============================================================================

shell: ## Open shell in API container
	docker-compose exec api bash

shell-db: ## Open psql shell in PostgreSQL
	docker-compose exec postgres psql -U agentx -d agentx

shell-redis: ## Open redis-cli shell
	docker-compose exec redis redis-cli -a agentx_redis_password

# ============================================================================
# Database Migrations
# ============================================================================

migrate: ## Run all pending migrations
	@echo "$(BLUE)Running database migrations...$(NC)"
	docker-compose exec api alembic upgrade head
	@echo "$(GREEN)✓ Migrations complete$(NC)"

migrate-create: ## Create a new migration (usage: make migrate-create MESSAGE="your message")
	@echo "$(BLUE)Creating new migration...$(NC)"
	docker-compose exec api alembic revision --autogenerate -m "$(MESSAGE)"
	@echo "$(GREEN)✓ Migration created$(NC)"

migrate-upgrade: ## Upgrade to specific revision (usage: make migrate-upgrade REVISION=+1)
	@echo "$(BLUE)Upgrading to revision $(REVISION)...$(NC)"
	docker-compose exec api alembic upgrade $(REVISION)
	@echo "$(GREEN)✓ Migration complete$(NC)"

migrate-downgrade: ## Downgrade to specific revision (usage: make migrate-downgrade REVISION=-1)
	@echo "$(BLUE)Downgrading to revision $(REVISION)...$(NC)"
	docker-compose exec api alembic downgrade $(REVISION)
	@echo "$(GREEN)✓ Rollback complete$(NC)"

migrate-history: ## Show migration history
	docker-compose exec api alembic history

migrate-current: ## Show current migration version
	docker-compose exec api alembic current

# ============================================================================
# Database Management
# ============================================================================

reset-db: ## Drop and recreate database (WARNING: destroys all data)
	@echo "$(RED)WARNING: This will destroy all data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "$(BLUE)Resetting database...$(NC)"; \
		docker-compose down -v; \
		docker-compose up -d postgres redis; \
		sleep 5; \
		docker-compose up -d api; \
		sleep 5; \
		$(MAKE) migrate; \
		echo "$(GREEN)✓ Database reset complete$(NC)"; \
	fi

backup: ## Backup database to file (usage: make backup FILE=backup.sql)
	@echo "$(BLUE)Backing up database...$(NC)"
	docker-compose exec -T postgres pg_dump -U agentx agentx > $(or $(FILE),backup_$(shell date +%Y%m%d_%H%M%S).sql)
	@echo "$(GREEN)✓ Backup complete: $(FILE)$(NC)"

restore: ## Restore database from file (usage: make restore FILE=backup.sql)
	@echo "$(BLUE)Restoring database from $(FILE)...$(NC)"
	docker-compose exec -T postgres psql -U agentx agentx < $(FILE)
	@echo "$(GREEN)✓ Restore complete$(NC)"

seed: ## Seed database with test data
	@echo "$(BLUE)Seeding database...$(NC)"
	docker-compose exec api python scripts/seed_db.py
	@echo "$(GREEN)✓ Database seeded$(NC)"

# ============================================================================
# Testing
# ============================================================================

test: ## Run all tests
	@echo "$(BLUE)Running tests...$(NC)"
	docker-compose exec api pytest tests/ -v
	@echo "$(GREEN)✓ Tests complete$(NC)"

test-unit: ## Run unit tests only
	@echo "$(BLUE)Running unit tests...$(NC)"
	docker-compose exec api pytest tests/unit/ -v

test-integration: ## Run integration tests only
	@echo "$(BLUE)Running integration tests...$(NC)"
	docker-compose exec api pytest tests/integration/ -v

test-coverage: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	docker-compose exec api pytest tests/ --cov=src --cov-report=html --cov-report=term
	@echo "$(GREEN)✓ Coverage report generated in htmlcov/$(NC)"

# ============================================================================
# Code Quality
# ============================================================================

lint: ## Run linters (ruff)
	@echo "$(BLUE)Running linters...$(NC)"
	docker-compose exec api ruff check src/
	@echo "$(GREEN)✓ Linting complete$(NC)"

format: ## Format code (black + ruff)
	@echo "$(BLUE)Formatting code...$(NC)"
	docker-compose exec api black src/
	docker-compose exec api ruff check --fix src/
	@echo "$(GREEN)✓ Formatting complete$(NC)"

type-check: ## Run type checker (mypy)
	@echo "$(BLUE)Running type checker...$(NC)"
	docker-compose exec api mypy src/
	@echo "$(GREEN)✓ Type checking complete$(NC)"

# ============================================================================
# Cleanup
# ============================================================================

clean: ## Clean up temporary files and caches
	@echo "$(BLUE)Cleaning up...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-volumes: ## Remove all Docker volumes (WARNING: destroys all data)
	@echo "$(RED)WARNING: This will destroy all data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "$(BLUE)Removing volumes...$(NC)"; \
		docker-compose down -v; \
		echo "$(GREEN)✓ Volumes removed$(NC)"; \
	fi

# ============================================================================
# Health & Monitoring
# ============================================================================

health: ## Check health of all services
	@echo "$(BLUE)Checking service health...$(NC)"
	@echo ""
	@echo "API:"
	@curl -s http://localhost:8000/health | python -m json.tool || echo "$(RED)✗ API not responding$(NC)"
	@echo ""
	@echo "PostgreSQL:"
	@docker-compose exec postgres pg_isready -U agentx && echo "$(GREEN)✓ PostgreSQL healthy$(NC)" || echo "$(RED)✗ PostgreSQL unhealthy$(NC)"
	@echo ""
	@echo "Redis:"
	@docker-compose exec redis redis-cli -a agentx_redis_password ping && echo "$(GREEN)✓ Redis healthy$(NC)" || echo "$(RED)✗ Redis unhealthy$(NC)"

stats: ## Show resource usage stats
	docker stats --no-stream

# ============================================================================
# Development Utilities
# ============================================================================

install: ## Install Python dependencies locally (for IDE support)
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

generate-keys: ## Generate JWT RSA key pair
	@echo "$(BLUE)Generating RSA key pair...$(NC)"
	mkdir -p .keys
	openssl genrsa -out .keys/jwt_private.pem 2048
	openssl rsa -in .keys/jwt_private.pem -pubout -out .keys/jwt_public.pem
	chmod 600 .keys/jwt_private.pem
	@echo "$(GREEN)✓ Keys generated in .keys/$(NC)"

docs: ## Generate API documentation
	@echo "$(BLUE)Generating API documentation...$(NC)"
	@echo "OpenAPI docs available at: http://localhost:8000/docs"
	@echo "ReDoc docs available at: http://localhost:8000/redoc"

# ============================================================================
# Quick Start
# ============================================================================

init: ## Initialize project (first-time setup)
	@echo "$(BLUE)Initializing AgentX Platform...$(NC)"
	cp .env.example .env
	$(MAKE) generate-keys
	$(MAKE) up
	sleep 10
	$(MAKE) migrate
	@echo ""
	@echo "$(GREEN)✓ Initialization complete!$(NC)"
	@echo ""
	@echo "API: http://localhost:8000"
	@echo "Docs: http://localhost:8000/docs"
	@echo "pgAdmin: http://localhost:5050"
	@echo ""
	@echo "Run 'make seed' to populate with test data"
```

## File: scripts/init-db.sql

```sql
-- AgentX Database Initialization Script
-- Runs on first PostgreSQL container startup

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pgvector";

-- Set default encoding and locale
ALTER DATABASE agentx SET timezone TO 'UTC';
ALTER DATABASE agentx SET client_encoding TO 'UTF8';
ALTER DATABASE agentx SET default_text_search_config TO 'pg_catalog.english';

-- Grant necessary privileges
GRANT ALL PRIVILEGES ON DATABASE agentx TO agentx;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO agentx;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO agentx;

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE 'AgentX database initialized successfully';
END $$;
```

## File: scripts/pgadmin-servers.json

```json
{
  "Servers": {
    "1": {
      "Name": "AgentX PostgreSQL",
      "Group": "Servers",
      "Host": "postgres",
      "Port": 5432,
      "MaintenanceDB": "agentx",
      "Username": "agentx",
      "SSLMode": "prefer",
      "PassFile": "/tmp/pgpassfile"
    }
  }
}
```

## File: requirements.txt

```txt
# AgentX Platform Python Dependencies

# FastAPI & ASGI Server
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-multipart==0.0.6

# Database
sqlalchemy[asyncio]==2.0.25
asyncpg==0.29.0
alembic==1.13.1
psycopg2-binary==2.9.9

# Redis
redis[hiredis]==5.0.1

# Authentication & Security
pyjwt[crypto]==2.8.0
cryptography==42.0.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# Validation
pydantic==2.5.3
pydantic-settings==2.1.0
email-validator==2.1.0

# Environment & Config
python-dotenv==1.0.0

# HTTP Client
httpx==0.26.0

# Date & Time
python-dateutil==2.8.2

# Utilities
python-json-logger==2.0.7
```

## File: requirements-dev.txt

```txt
# Development Dependencies

# Testing
pytest==7.4.4
pytest-asyncio==0.23.3
pytest-cov==4.1.0
pytest-mock==3.12.0
httpx==0.26.0

# Code Quality
ruff==0.1.14
black==24.1.1
mypy==1.8.0
isort==5.13.2

# Type Stubs
types-redis==4.6.0.20240106
types-python-dateutil==2.8.19.20240106

# Documentation
mkdocs==1.5.3
mkdocs-material==9.5.6

# Database Tools
pgcli==4.0.1
```