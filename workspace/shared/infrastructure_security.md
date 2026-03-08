# AgentX Infrastructure Security Review

**Reviewer:** MARCUS (did:agentx:marcus-001)  
**Scope:** Docker Compose, Dockerfiles, Kubernetes manifests, TLS configuration  
**Review Date:** Phase 2 Security Gate  
**Artifacts Reviewed:** `k8s/*.yaml`, inferred `docker-compose.yml`, `Dockerfile`

---

## Executive Summary

| **Infrastructure Security Posture** | **CONDITIONAL PASS** |
|-------------------------------------|----------------------|
| **Phase 3 Authorization**           | ❌ BLOCKED — 5 CRITICAL findings must be resolved |

BRUNO's Kubernetes manifests show **good security foundations** — the API deployment includes `runAsNonRoot`, `readOnlyRootFilesystem`, capability dropping, and proper external secrets management. However, **critical gaps exist** in network isolation (no NetworkPolicies), database/Redis security contexts, and TLS configuration. The Docker Compose setup (inferred) lacks production hardening.

### Critical Gaps

1. **No NetworkPolicies** — All pods can communicate with all other pods (flat network)
2. **PostgreSQL/Redis running as root** — Database containers have no security context
3. **No internal mTLS** — Service-to-service traffic is unencrypted
4. **Missing Ingress TLS configuration** — No cert-manager integration shown
5. **`:latest` image tags** — Unpinned images in production

---

## Docker Security Findings

### Docker Compose Analysis (Inferred + Required Configuration)

Based on the Kubernetes manifests and standard patterns, here's the security review of the likely Docker Compose setup:

#### Finding INF-D01: Running Containers as Root [CRITICAL]

```yaml
# ❌ INSECURE: docker-compose.yml (likely current state)
version: '3.8'
services:
  api:
    image: agentx/api:latest  # Unpinned!
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@postgres:5432/agentx  # Secret in env!
    # No user specified = runs as root
    
  postgres:
    image: postgres:latest  # Unpinned!
    environment:
      - POSTGRES_PASSWORD=supersecret  # Plaintext secret!
    volumes:
      - postgres_data:/var/lib/postgresql/data
    # No user specified = runs as root
    
  redis:
    image: redis:latest  # Unpinned!
    # No authentication configured
    # Runs as root
```

#### Secure Docker Compose Configuration

```yaml
# File: docker-compose.yml (SECURE)

version: '3.8'

# ============================================================================
# SECURE DOCKER COMPOSE FOR AGENTX
# ============================================================================

x-common-security: &common-security
  security_opt:
    - no-new-privileges:true
  read_only: true
  tmpfs:
    - /tmp:mode=1777,size=64m
  cap_drop:
    - ALL

services:
  # --------------------------------------------------------------------------
  # API SERVICE
  # --------------------------------------------------------------------------
  api:
    image: ghcr.io/agentx/api:1.0.0-sha-a1b2c3d  # Pinned to digest
    build:
      context: .
      dockerfile: Dockerfile
      args:
        - BUILD_DATE=${BUILD_DATE}
        - VCS_REF=${VCS_REF}
    <<: *common-security
    user: "1000:1000"  # Non-root user
    ports:
      - "127.0.0.1:8000:8000"  # Bind to localhost only (use reverse proxy)
    environment:
      # Non-sensitive config only
      - LOG_LEVEL=INFO
      - ENVIRONMENT=production
    secrets:
      - db_credentials
      - redis_credentials
      - jwt_private_key
      - jwt_public_key
      - anthropic_api_key
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M
    networks:
      - frontend
      - backend
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    cap_add: []  # No additional capabilities needed

  # --------------------------------------------------------------------------
  # POSTGRESQL SERVICE
  # --------------------------------------------------------------------------
  postgres:
    image: postgres:16.2-alpine@sha256:abc123...  # Pinned to digest
    <<: *common-security
    read_only: false  # Postgres needs write access to data dir
    user: "999:999"  # postgres user in container
    environment:
      - POSTGRES_USER_FILE=/run/secrets/postgres_user
      - POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password
      - POSTGRES_DB=agentx
      # Security settings
      - POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=scram-sha-256
    secrets:
      - postgres_user
      - postgres_password
    volumes:
      - postgres_data:/var/lib/postgresql/data:rw
      - ./postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro
      - ./postgres/postgresql.conf:/etc/postgresql/postgresql.conf:ro
      - postgres_run:/var/run/postgresql:rw
    tmpfs:
      - /tmp:mode=1777,size=64m
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$(cat /run/secrets/postgres_user) -d agentx"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G
    networks:
      - backend
    # CRITICAL: Not exposed to host - only backend network
    # ports: REMOVED

  # --------------------------------------------------------------------------
  # REDIS SERVICE
  # --------------------------------------------------------------------------
  redis:
    image: redis:7.2-alpine@sha256:def456...  # Pinned to digest
    <<: *common-security
    user: "999:999"  # redis user
    command: >
      redis-server
      --requirepass /run/secrets/redis_password
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --bind 0.0.0.0
      --protected-mode yes
      --rename-command FLUSHALL ""
      --rename-command FLUSHDB ""
      --rename-command DEBUG ""
      --rename-command CONFIG ""
    secrets:
      - redis_password
    volumes:
      - redis_data:/data:rw
    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "-a", "$$(cat /run/secrets/redis_password)", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 256M
    networks:
      - backend
    # CRITICAL: Not exposed to host
    # ports: REMOVED

# ============================================================================
# SECRETS (Docker Secrets - not environment variables)
# ============================================================================
secrets:
  db_credentials:
    file: ./secrets/db_credentials.json
  redis_credentials:
    file: ./secrets/redis_password.txt
  postgres_user:
    file: ./secrets/postgres_user.txt
  postgres_password:
    file: ./secrets/postgres_password.txt
  redis_password:
    file: ./secrets/redis_password.txt
  jwt_private_key:
    file: ./secrets/jwt_private.pem
  jwt_public_key:
    file: ./secrets/jwt_public.pem
  anthropic_api_key:
    file: ./secrets/anthropic_api_key.txt

# ============================================================================
# NETWORKS (Isolated)
# ============================================================================
networks:
  frontend:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.enable_ip_masquerade: "true"
  backend:
    driver: bridge
    internal: true  # No external access - isolated network
    driver_opts:
      com.docker.network.bridge.enable_ip_masquerade: "false"

# ============================================================================
# VOLUMES (Encrypted at rest via Docker/host)
# ============================================================================
volumes:
  postgres_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /encrypted/agentx/postgres  # Encrypted filesystem
  postgres_run:
    driver: local
  redis_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /encrypted/agentx/redis
```

### Secure Dockerfile

```dockerfile
# File: Dockerfile

# ============================================================================
# STAGE 1: Build
# ============================================================================
FROM python:3.11-slim-bookworm@sha256:abc123... AS builder

# Security: Don't run pip as root where possible
WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (layer caching)
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies with security checks
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    # Security: Audit dependencies
    pip install --no-cache-dir pip-audit && \
    pip-audit --strict --progress-spinner off

# ============================================================================
# STAGE 2: Production
# ============================================================================
FROM python:3.11-slim-bookworm@sha256:abc123... AS production

# Security labels
LABEL maintainer="security@agentx.ai" \
      org.opencontainers.image.title="AgentX API" \
      org.opencontainers.image.description="AgentX Platform API Server" \
      org.opencontainers.image.vendor="AgentX" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/agentx/platform"

# Security: Create non-root user
RUN groupadd --gid 1000 agentx && \
    useradd --uid 1000 --gid 1000 --shell /bin/false --create-home agentx

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /var/cache/apt/archives/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code (owned by agentx user)
COPY --chown=agentx:agentx src/ ./src/
COPY --chown=agentx:agentx alembic/ ./alembic/
COPY --chown=agentx:agentx alembic.ini ./

# Create necessary directories with correct permissions
RUN mkdir -p /app/.keys /tmp && \
    chown -R agentx:agentx /app /tmp

# Security: Remove shell and other unnecessary tools
RUN rm -rf /bin/sh /bin/bash /usr/bin/apt* /usr/bin/dpkg* 2>/dev/null || true

# Security: Switch to non-root user
USER 1000:1000

# Security: Set restrictive umask
ENV UMASK=0077

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

# Expose port (documentation only - actual binding controlled by orchestrator)
EXPOSE 8000

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--no-access-log"]
```

---

## Kubernetes Security Hardening

### Finding INF-K01: Missing NetworkPolicies [CRITICAL]

The provided manifests contain no NetworkPolicy resources. This means:
- Any pod can communicate with any other pod
- Compromised pod can reach database directly
- Lateral movement is unrestricted

#### Complete NetworkPolicy Configuration

```yaml
# File: k8s/network-policies.yaml

# ============================================================================
# AGENTX NETWORK POLICIES
# Default deny all, then allow specific traffic
# ============================================================================

---
# DEFAULT DENY ALL INGRESS/EGRESS IN NAMESPACE
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
    security.agentx.ai/policy: default-deny
spec:
  podSelector: {}  # Applies to all pods in namespace
  policyTypes:
    - Ingress
    - Egress
  # No ingress/egress rules = deny all

---
# API PODS: Ingress from Ingress Controller only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-ingress
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: api
  policyTypes:
    - Ingress
  ingress:
    # Allow from NGINX Ingress Controller
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
          podSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8000
    # Allow from Prometheus for metrics scraping
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app: prometheus
      ports:
        - protocol: TCP
          port: 8000

---
# API PODS: Egress to PostgreSQL, Redis, DNS, and external APIs
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-egress
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: api
  policyTypes:
    - Egress
  egress:
    # Allow DNS resolution (kube-dns)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    
    # Allow PostgreSQL
    - to:
        - podSelector:
            matchLabels:
              app: agentx
              component: postgres
      ports:
        - protocol: TCP
          port: 5432
    
    # Allow Redis
    - to:
        - podSelector:
            matchLabels:
              app: agentx
              component: redis
      ports:
        - protocol: TCP
          port: 6379
    
    # Allow external HTTPS (Anthropic API, etc.)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8      # Block internal ranges
              - 172.16.0.0/12   # Block internal ranges
              - 192.168.0.0/16  # Block internal ranges
      ports:
        - protocol: TCP
          port: 443

---
# POSTGRESQL: Ingress from API pods only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-ingress
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: postgres
  policyTypes:
    - Ingress
  ingress:
    # Only allow from API pods
    - from:
        - podSelector:
            matchLabels:
              app: agentx
              component: api
      ports:
        - protocol: TCP
          port: 5432
    # Allow from backup job
    - from:
        - podSelector:
            matchLabels:
              app: agentx
              component: backup
      ports:
        - protocol: TCP
          port: 5432

---
# POSTGRESQL: Egress for DNS only (no external connections needed)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-egress
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: postgres
  policyTypes:
    - Egress
  egress:
    # DNS only
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53

---
# REDIS: Ingress from API pods only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: redis-ingress
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: redis
  policyTypes:
    - Ingress
  ingress:
    # Only allow from API pods
    - from:
        - podSelector:
            matchLabels:
              app: agentx
              component: api
      ports:
        - protocol: TCP
          port: 6379

---
# REDIS: Egress for DNS only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: redis-egress
  namespace: agentx
  labels:
    app.kubernetes.io/part-of: agentx-platform
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: redis
  policyTypes:
    - Egress
  egress:
    # DNS only
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
```

### Finding INF-K02: PostgreSQL Pod Missing Security Context [CRITICAL]

```yaml
# File: k8s/postgres-deployment.yaml (SECURE)

apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: agentx
  labels:
    app: agentx
    component: postgres
spec:
  replicas: 1
  strategy:
    type: Recreate  # StatefulSet preferred for production
  selector:
    matchLabels:
      app: agentx
      component: postgres
  template:
    metadata:
      labels:
        app: agentx
        component: postgres
      annotations:
        seccomp.security.alpha.kubernetes.io/pod: runtime/default
    spec:
      serviceAccountName: agentx-postgres
      securityContext:
        runAsNonRoot: true
        runAsUser: 999      # postgres user
        runAsGroup: 999
        fsGroup: 999
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile:
          type: RuntimeDefault
      
      # Anti-affinity: don't schedule on same node as API (if possible)
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: agentx
                topologyKey: kubernetes.io/hostname
      
      containers:
        - name: postgres
          image: postgres:16.2-alpine@sha256:1234567890abcdef...
          imagePullPolicy: Always
          
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false  # Postgres needs writes
            runAsNonRoot: true
            runAsUser: 999
            capabilities:
              drop:
                - ALL
              # Postgres needs no special capabilities
          
          ports:
            - name: postgres
              containerPort: 5432
              protocol: TCP
          
          env:
            - name: POSTGRES_DB
              value: agentx
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: password
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 2000m
              memory: 4Gi
          
          livenessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U $(POSTGRES_USER) -d agentx
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 6
          
          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U $(POSTGRES_USER) -d agentx
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
            - name: config
              mountPath: /etc/postgresql/postgresql.conf
              subPath: postgresql.conf
              readOnly: true
            - name: config
              mountPath: /etc/postgresql/pg_hba.conf
              subPath: pg_hba.conf
              readOnly: true
            - name: tls
              mountPath: /etc/postgresql/tls
              readOnly: true
            - name: tmp
              mountPath: /tmp
            - name: run
              mountPath: /var/run/postgresql
      
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: postgres-data
        - name: config
          configMap:
            name: postgres-config
        - name: tls
          secret:
            secretName: postgres-tls
            defaultMode: 0400
        - name: tmp
          emptyDir:
            sizeLimit: 100Mi
        - name: run
          emptyDir:
            medium: Memory
            sizeLimit: 10Mi

---
# PostgreSQL configuration hardening
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
  namespace: agentx
data:
  postgresql.conf: |
    # Connection settings
    listen_addresses = '*'
    port = 5432
    max_connections = 200
    
    # Authentication
    password_encryption = scram-sha-256
    
    # SSL/TLS (require encrypted connections)
    ssl = on
    ssl_cert_file = '/etc/postgresql/tls/tls.crt'
    ssl_key_file = '/etc/postgresql/tls/tls.key'
    ssl_ca_file = '/etc/postgresql/tls/ca.crt'
    ssl_min_protocol_version = 'TLSv1.3'
    ssl_ciphers = 'HIGH:!aNULL:!MD5:!3DES'
    
    # Logging
    log_destination = 'stderr'
    logging_collector = off
    log_statement = 'ddl'
    log_connections = on
    log_disconnections = on
    log_duration = off
    log_min_duration_statement = 1000
    
    # Security
    row_security = on
    
    # Performance
    shared_buffers = 256MB
    effective_cache_size = 1GB
    work_mem = 16MB
    maintenance_work_mem = 128MB
    
  pg_hba.conf: |
    # TYPE  DATABASE    USER            ADDRESS         METHOD
    # Reject all non-SSL connections
    hostnossl all        all             all             reject
    # Allow SSL connections with SCRAM authentication only
    hostssl   agentx     agentx_api      10.0.0.0/8      scram-sha-256
    hostssl   agentx     agentx_backup   10.0.0.0/8      scram-sha-256
    # Reject everything else
    host      all        all             all             reject
```

### Finding INF-K03: Redis Pod Missing Security Context [CRITICAL]

```yaml
# File: k8s/redis-deployment.yaml (SECURE)

apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: agentx
  labels:
    app: agentx
    component: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: agentx
      component: redis
  template:
    metadata:
      labels:
        app: agentx
        component: redis
      annotations:
        seccomp.security.alpha.kubernetes.io/pod: runtime/default
    spec:
      serviceAccountName: agentx-redis
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
        seccompProfile:
          type: RuntimeDefault
      
      containers:
        - name: redis
          image: redis:7.2-alpine@sha256:abcdef123456...
          imagePullPolicy: Always
          
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 999
            capabilities:
              drop:
                - ALL
          
          command:
            - redis-server
            - /etc/redis/redis.conf
            - --requirepass
            - $(REDIS_PASSWORD)
          
          env:
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: redis-credentials
                  key: password
          
          ports:
            - name: redis
              containerPort: 6379
              protocol: TCP
          
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          
          livenessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - redis-cli -a $REDIS_PASSWORD ping | grep -q PONG
            initialDelaySeconds: 15
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          
          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - redis-cli -a $REDIS_PASSWORD ping | grep -q PONG
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          
          volumeMounts:
            - name: data
              mountPath: /data
            - name: config
              mountPath: /etc/redis
              readOnly: true
            - name: tmp
              mountPath: /tmp
      
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: redis-data
        - name: config
          configMap:
            name: redis-config
        - name: tmp
          emptyDir:
            sizeLimit: 10Mi

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: agentx
data:
  redis.conf: |
    # Network
    bind 0.0.0.0
    port 6379
    protected-mode yes
    tcp-backlog 511
    timeout 0
    tcp-keepalive 300
    
    # TLS (optional but recommended)
    # tls-port 6379
    # port 0
    # tls-cert-file /etc/redis/tls/tls.crt
    # tls-key-file /etc/redis/tls/tls.key
    # tls-ca-cert-file /etc/redis/tls/ca.crt
    # tls-auth-clients yes
    
    # Security - disable dangerous commands
    rename-command FLUSHALL ""
    rename-command FLUSHDB ""
    rename-command DEBUG ""
    rename-command CONFIG ""
    rename-command SHUTDOWN SHUTDOWN_SEKRET_CMD
    rename-command SLAVEOF ""
    rename-command REPLICAOF ""
    rename-command BGREWRITEAOF ""
    rename-command BGSAVE ""
    rename-command SAVE ""
    
    # Memory
    maxmemory 450mb
    maxmemory-policy allkeys-lru
    
    # Persistence (AOF for durability)
    appendonly yes
    appendfsync everysec
    no-appendfsync-on-rewrite no
    auto-aof-rewrite-percentage 100
    auto-aof-rewrite-min-size 64mb
    
    # Logging
    loglevel notice
    logfile ""
    
    # Slow log
    slowlog-log-slower-than 10000
    slowlog-max-len 128
```

### Finding INF-K04: Missing RBAC Least Privilege [HIGH]

```yaml
# File: k8s/rbac.yaml

---
# Service Account for API pods
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agentx-api
  namespace: agentx
  labels:
    app: agentx
    component: api
automountServiceAccountToken: false  # Disable unless needed

---
# Service Account for PostgreSQL
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agentx-postgres
  namespace: agentx
  labels:
    app: agentx
    component: postgres
automountServiceAccountToken: false

---
# Service Account for Redis
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agentx-redis
  namespace: agentx
  labels:
    app: agentx
    component: redis
automountServiceAccountToken: false

---
# Role for API pods (minimal permissions)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: agentx-api-role
  namespace: agentx
rules:
  # API pods need to read their own secrets
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["agentx-secrets", "agentx-jwt-keys"]
    verbs: ["get"]
  # Read ConfigMaps
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["agentx-config"]
    verbs: ["get"]

---
# Bind role to API service account
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: agentx-api-rolebinding
  namespace: agentx
subjects:
  - kind: ServiceAccount
    name: agentx-api
    namespace: agentx
roleRef:
  kind: Role
  name: agentx-api-role
  apiGroup: rbac.authorization.k8s.io

---
# PodSecurityPolicy (if using PSP - deprecated but still used in some clusters)
# Or PodSecurity admission (for K8s 1.25+)
apiVersion: v1
kind: Namespace
metadata:
  name: agentx
  labels:
    name: agentx
    # Enable Pod Security Standards (Restricted)
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
```

### Finding INF-K05: API Deployment Image Tag `:latest` [HIGH]

Current manifest shows:
```yaml
image: ghcr.io/agentx/api:latest  # INSECURE
```

#### Fixed API Deployment

```yaml
# File: k8s/api-deployment.yaml (SECURE - key changes highlighted)

apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentx-api
  namespace: agentx
  labels:
    app: agentx
    component: api
    version: v1.0.0
  annotations:
    kubernetes.io/change-cause: "Deploy v1.0.0 - security hardening"
spec:
  replicas: 3
  revisionHistoryLimit: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: agentx
      component: api
  template:
    metadata:
      labels:
        app: agentx
        component: api
        version: v1.0.0
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
        # Force redeployment on secret change
        checksum/secrets: "${SECRETS_CHECKSUM}"
    spec:
      serviceAccountName: agentx-api
      automountServiceAccountToken: false  # Disable K8s token mounting
      
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      
      # Topology spread for HA
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: agentx
              component: api
      
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: component
                    operator: In
                    values:
                      - api
              topologyKey: kubernetes.io/hostname
      
      containers:
        - name: api
          # CRITICAL: Pinned image with SHA256 digest
          image: ghcr.io/agentx/api:1.0.0@sha256:a1b2c3d4e5f6...
          imagePullPolicy: Always
          
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 1000
            capabilities:
              drop:
                - ALL
          
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
          
          envFrom:
            - configMapRef:
                name: agentx-config
          
          env:
            # Secrets as individual env vars (not bulk secretRef for audit)
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: DATABASE_URL
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: REDIS_URL
            - name: SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: SECRET_KEY
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: ANTHROPIC_API_KEY
          
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          
          # Probes don't expose sensitive data
          livenessProbe:
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          
          readinessProbe:
            httpGet:
              path: /health/ready
              port: http
              scheme: HTTP
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          
          startupProbe:
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 30
          
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: keys
              mountPath: /app/.keys
              readOnly: true
      
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 100Mi
        - name: keys
          secret:
            secretName: agentx-jwt-keys
            defaultMode: 0400
```

---

## TLS / Certificate Management

### Finding INF-K06: Missing TLS Configuration [CRITICAL]

No Ingress TLS or cert-manager configuration provided.

#### Complete TLS Implementation

```yaml
# File: k8s/cert-manager.yaml

---
# ClusterIssuer for Let's Encrypt (Production)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: security@agentx.ai
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
      - http01:
          ingress:
            class: nginx
        selector:
          dnsZones:
            - agentx.ai

---
# ClusterIssuer for Let's Encrypt (Staging - for testing)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    email: security@agentx.ai
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
      - http01:
          ingress:
            class: nginx

---
# Certificate for API domain
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: agentx-api-tls
  namespace: agentx
spec:
  secretName: agentx-api-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - api.agentx.ai
    - app.agentx.ai
  duration: 2160h    # 90 days
  renewBefore: 720h  # 30 days before expiry
  privateKey:
    algorithm: ECDSA
    size: 256
```

```yaml
# File: k8s/ingress.yaml

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: agentx-api-ingress
  namespace: agentx
  labels:
    app: agentx
    component: ingress
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    
    # Security headers
    nginx.ingress.kubernetes.io/configuration-snippet: |
      more_set_headers "X-Frame-Options: DENY";
      more_set_headers "X-Content-Type-Options: nosniff";
      more_set_headers "X-XSS-Protection: 1; mode=block";
      more_set_headers "Referrer-Policy: strict-origin-when-cross-origin";
      more_set_headers "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'";
      more_set_headers "Permissions-Policy: geolocation=(), microphone=(), camera=()";
    
    # HSTS (2 years)
    nginx.ingress.kubernetes.io/hsts: "true"
    nginx.ingress.kubernetes.io/hsts-max-age: "63072000"
    nginx.ingress.kubernetes.io/hsts-include-subdomains: "true"
    nginx.ingress.kubernetes.io/hsts-preload: "true"
    
    # SSL configuration
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/ssl-protocols: "TLSv1.3"
    nginx.ingress.kubernetes.io/ssl-ciphers: "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
    
    # Rate limiting at ingress level
    nginx.ingress.kubernetes.io/limit-rps: "100"
    nginx.ingress.kubernetes.io/limit-connections: "50"
    nginx.ingress.kubernetes.io/limit-rpm: "1000"
    
    # Request size limits
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    
    # Timeouts
    nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "10"
    
    # WebSocket support
    nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
    nginx.ingress.kubernetes.io/upstream-hash-by: "$binary_remote_addr"
    
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.agentx.ai
        - app.agentx.ai
      secretName: agentx-api-tls
  rules:
    - host: api.agentx.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: agentx-api
                port:
                  number: 8000
    - host: app.agentx.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: agentx-api
                port:
                  number: 8000
```

### Internal mTLS with cert-manager

```yaml
# File: k8s/internal-tls.yaml

---
# Internal CA for service-to-service mTLS
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: agentx-internal-ca
  namespace: agentx
spec:
  selfSigned: {}

---
# CA Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: agentx-internal-ca-cert
  namespace: agentx
spec:
  isCA: true
  secretName: agentx-internal-ca
  commonName: agentx-internal-ca
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: agentx-internal-ca
    kind: Issuer
    group: cert-manager.io

---
# Issuer using the CA
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: agentx-internal-issuer
  namespace: agentx
spec:
  ca:
    secretName: agentx-internal-ca

---
# PostgreSQL TLS Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: postgres-tls
  namespace: agentx
spec:
  secretName: postgres-tls
  issuerRef:
    name: agentx-internal-issuer
    kind: Issuer
  dnsNames:
    - postgres-service
    - postgres-service.agentx
    - postgres-service.agentx.svc
    - postgres-service.agentx.svc.cluster.local
  duration: 8760h   # 1 year
  renewBefore: 720h # 30 days
  privateKey:
    algorithm: ECDSA
    size: 256

---
# Redis TLS Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: redis-tls
  namespace: agentx
spec:
  secretName: redis-tls
  issuerRef:
    name: agentx-internal-issuer
    kind: Issuer
  dnsNames:
    - redis-service
    - redis-service.agentx
    - redis-service.agentx.svc
    - redis-service.agentx.svc.cluster.local
  duration: 8760h
  renewBefore: 720h
  privateKey:
    algorithm: ECDSA
    size: 256

---
# API Service Certificate (for mTLS client auth)
apiVersion: cert-manager.io/v1
kind