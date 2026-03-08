## File: k8s/namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: agentx
  labels:
    name: agentx
    env: production
    managed-by: kubernetes
    app.kubernetes.io/name: agentx
    app.kubernetes.io/part-of: agentx-platform
```

## File: k8s/configmap.yaml

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agentx-config
  namespace: agentx
  labels:
    app: agentx
    component: config
data:
  # Logging
  LOG_LEVEL: "INFO"
  LOG_FORMAT: "json"
  
  # CORS
  CORS_ORIGINS: "https://agentx.ai,https://app.agentx.ai,https://www.agentx.ai"
  
  # Database Pool Configuration
  DB_POOL_SIZE: "20"
  DB_MAX_OVERFLOW: "10"
  DB_POOL_TIMEOUT: "30"
  DB_POOL_RECYCLE: "3600"
  DB_POOL_PRE_PING: "true"
  
  # Redis Configuration
  REDIS_MAX_CONNECTIONS: "50"
  
  # JWT Configuration
  JWT_ALGORITHM: "RS256"
  ACCESS_TOKEN_EXPIRE_MINUTES: "15"
  REFRESH_TOKEN_EXPIRE_DAYS: "7"
  
  # Rate Limiting
  RATE_LIMIT_WINDOW: "60"
  RATE_LIMIT_UNVERIFIED: "10"
  RATE_LIMIT_VERIFIED: "60"
  RATE_LIMIT_TRUSTED: "200"
  RATE_LIMIT_ELITE: "600"
  
  # Cache TTL (seconds)
  AGENT_PROFILE_TTL: "300"
  TRUST_SCORE_TTL: "60"
  POST_FEED_TTL: "30"
  CAPABILITY_TTL: "3600"
  SESSION_TTL: "86400"
  
  # WebSocket
  WS_HEARTBEAT_INTERVAL: "30"
  WS_MAX_CONNECTIONS_PER_AGENT: "5"
  
  # Environment
  ENVIRONMENT: "production"
  
  # Feature Flags
  ENABLE_GOVERNANCE: "true"
  ENABLE_TOKEN_TRANSFERS: "true"
  ENABLE_COLLECTIVES: "true"
  ENABLE_WEBSOCKET: "true"
```

## File: k8s/secrets.yaml

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: agentx-secrets
  namespace: agentx
  labels:
    app: agentx
    component: secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: SecretStore
  target:
    name: agentx-secrets
    creationPolicy: Owner
    template:
      engineVersion: v2
      data:
        DATABASE_URL: "postgresql+asyncpg://{{ .postgres_user }}:{{ .postgres_password }}@postgres-service.agentx.svc.cluster.local:5432/{{ .postgres_db }}"
        REDIS_URL: "redis://:{{ .redis_password }}@redis-service.agentx.svc.cluster.local:6379/0"
        SECRET_KEY: "{{ .secret_key }}"
        ANTHROPIC_API_KEY: "{{ .anthropic_api_key }}"
        POSTGRES_USER: "{{ .postgres_user }}"
        POSTGRES_PASSWORD: "{{ .postgres_password }}"
        POSTGRES_DB: "{{ .postgres_db }}"
        REDIS_PASSWORD: "{{ .redis_password }}"
  dataFrom:
    - extract:
        key: agentx/production
---
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: aws-secrets-manager
  namespace: agentx
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: agentx-api
```

## File: k8s/api-deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentx-api
  namespace: agentx
  labels:
    app: agentx
    component: api
    version: v1
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
        version: v1
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: agentx-api
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: component
                      operator: In
                      values:
                        - api
                topologyKey: kubernetes.io/hostname
      containers:
        - name: api
          image: ghcr.io/agentx/api:latest
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
          envFrom:
            - configMapRef:
                name: agentx-config
            - secretRef:
                name: agentx-secrets
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          livenessProbe:
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            successThreshold: 1
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            successThreshold: 1
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            successThreshold: 1
            failureThreshold: 30
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 1000
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: keys
              mountPath: /app/.keys
              readOnly: true
      volumes:
        - name: tmp
          emptyDir: {}
        - name: keys
          secret:
            secretName: agentx-jwt-keys
            defaultMode: 0400
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agentx-api
  namespace: agentx
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/agentx-api-role
```

## File: k8s/api-service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: agentx-api
  namespace: agentx
  labels:
    app: agentx
    component: api
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-backend-protocol: "tcp"
spec:
  type: ClusterIP
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800
  selector:
    app: agentx
    component: api
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
    - name: https
      port: 443
      targetPort: http
      protocol: TCP
```

## File: k8s/api-ingress.yaml

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: agentx-api
  namespace: agentx
  labels:
    app: agentx
    component: ingress
  annotations:
    # Ingress class
    kubernetes.io/ingress.class: nginx
    
    # TLS/SSL
    cert-manager.io/cluster-issuer: letsencrypt-prod
    cert-manager.io/acme-challenge-type: http01
    
    # Security headers
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/ssl-protocols: "TLSv1.2 TLSv1.3"
    nginx.ingress.kubernetes.io/ssl-ciphers: "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
    
    # CORS
    nginx.ingress.kubernetes.io/enable-cors: "true"
    nginx.ingress.kubernetes.io/cors-allow-origin: "https://agentx.ai,https://app.agentx.ai"
    nginx.ingress.kubernetes.io/cors-allow-methods: "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    nginx.ingress.kubernetes.io/cors-allow-credentials: "true"
    
    # WebSocket support
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/websocket-services: "agentx-api"
    nginx.ingress.kubernetes.io/configuration-snippet: |
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_http_version 1.1;
    
    # Rate limiting
    nginx.ingress.kubernetes.io/limit-rps: "100"
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "2"
    
    # Request size
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    
    # Timeouts
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
    
    # Custom headers
    nginx.ingress.kubernetes.io/configuration-snippet: |
      more_set_headers "X-Frame-Options: DENY";
      more_set_headers "X-Content-Type-Options: nosniff";
      more_set_headers "X-XSS-Protection: 1; mode=block";
      more_set_headers "Strict-Transport-Security: max-age=31536000; includeSubDomains; preload";
      more_set_headers "Referrer-Policy: strict-origin-when-cross-origin";
      more_set_headers "Permissions-Policy: geolocation=(), microphone=(), camera=()";
spec:
  tls:
    - hosts:
        - api.agentx.ai
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
                  number: 80
```

## File: k8s/hpa.yaml

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agentx-api-hpa
  namespace: agentx
  labels:
    app: agentx
    component: api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agentx-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
        - type: Pods
          value: 2
          periodSeconds: 60
      selectPolicy: Min
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 30
        - type: Pods
          value: 4
          periodSeconds: 30
      selectPolicy: Max
```

## File: k8s/postgres-statefulset.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-service
  namespace: agentx
  labels:
    app: postgres
spec:
  type: ClusterIP
  clusterIP: None
  selector:
    app: postgres
  ports:
    - name: postgres
      port: 5432
      targetPort: 5432
      protocol: TCP
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: agentx
  labels:
    app: postgres
spec:
  serviceName: postgres-service
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      securityContext:
        fsGroup: 999
        runAsUser: 999
        runAsNonRoot: true
      containers:
        - name: postgres
          image: pgvector/pgvector:pg16
          imagePullPolicy: IfNotPresent
          ports:
            - name: postgres
              containerPort: 5432
              protocol: TCP
          env:
            - name: POSTGRES_DB
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: POSTGRES_DB
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: POSTGRES_USER
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: POSTGRES_PASSWORD
            - name: POSTGRES_INITDB_ARGS
              value: "-E UTF8 --locale=en_US.UTF-8"
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
                - pg_isready -U $POSTGRES_USER -d $POSTGRES_DB
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            successThreshold: 1
            failureThreshold: 3
          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U $POSTGRES_USER -d $POSTGRES_DB
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            successThreshold: 1
            failureThreshold: 3
          volumeMounts:
            - name: postgres-storage
              mountPath: /var/lib/postgresql/data
            - name: postgres-config
              mountPath: /etc/postgresql/postgresql.conf
              subPath: postgresql.conf
      volumes:
        - name: postgres-config
          configMap:
            name: postgres-config
  volumeClaimTemplates:
    - metadata:
        name: postgres-storage
        labels:
          app: postgres
      spec:
        accessModes:
          - ReadWriteOnce
        storageClassName: gp3-encrypted
        resources:
          requests:
            storage: 50Gi
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
  namespace: agentx
data:
  postgresql.conf: |
    # Performance tuning
    max_connections = 200
    shared_buffers = 1GB
    effective_cache_size = 3GB
    maintenance_work_mem = 256MB
    checkpoint_completion_target = 0.9
    wal_buffers = 16MB
    default_statistics_target = 100
    random_page_cost = 1.1
    effective_io_concurrency = 200
    work_mem = 5242kB
    min_wal_size = 1GB
    max_wal_size = 4GB
    
    # Logging
    log_destination = 'stderr'
    logging_collector = on
    log_directory = 'log'
    log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
    log_rotation_age = 1d
    log_rotation_size = 100MB
    log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
    log_checkpoints = on
    log_connections = on
    log_disconnections = on
    log_duration = off
    log_lock_waits = on
    log_min_duration_statement = 1000
    
    # Security
    ssl = off
    password_encryption = scram-sha-256
```

## File: k8s/redis-statefulset.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: redis-service
  namespace: agentx
  labels:
    app: redis
spec:
  type: ClusterIP
  clusterIP: None
  selector:
    app: redis
  ports:
    - name: redis
      port: 6379
      targetPort: 6379
      protocol: TCP
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: agentx
  labels:
    app: redis
spec:
  serviceName: redis-service
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      securityContext:
        fsGroup: 999
        runAsUser: 999
        runAsNonRoot: true
      containers:
        - name: redis
          image: redis:7-alpine
          imagePullPolicy: IfNotPresent
          command:
            - redis-server
          args:
            - /etc/redis/redis.conf
            - --requirepass
            - $(REDIS_PASSWORD)
          ports:
            - name: redis
              containerPort: 6379
              protocol: TCP
          env:
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: agentx-secrets
                  key: REDIS_PASSWORD
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 2Gi
          livenessProbe:
            exec:
              command:
                - redis-cli
                - --raw
                - incr
                - ping
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            successThreshold: 1
            failureThreshold: 3
          readinessProbe:
            exec:
              command:
                - redis-cli
                - --raw
                - incr
                - ping
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            successThreshold: 1
            failureThreshold: 3
          volumeMounts:
            - name: redis-storage
              mountPath: /data
            - name: redis-config
              mountPath: /etc/redis
      volumes:
        - name: redis-config
          configMap:
            name: redis-config
  volumeClaimTemplates:
    - metadata:
        name: redis-storage
        labels:
          app: redis
      spec:
        accessModes:
          - ReadWriteOnce
        storageClassName: gp3-encrypted
        resources:
          requests:
            storage: 10Gi
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
    protected-mode yes
    port 6379
    tcp-backlog 511
    timeout 0
    tcp-keepalive 300
    
    # Persistence
    appendonly yes
    appendfilename "appendonly.aof"
    appendfsync everysec
    no-appendfsync-on-rewrite no
    auto-aof-rewrite-percentage 100
    auto-aof-rewrite-min-size 64mb
    
    # Memory management
    maxmemory 512mb
    maxmemory-policy allkeys-lru
    
    # Slow log
    slowlog-log-slower-than 10000
    slowlog-max-len 128
    
    # Limits
    maxclients 10000
    
    # Performance
    databases 16
    save 900 1
    save 300 10
    save 60 10000
    stop-writes-on-bgsave-error yes
    rdbcompression yes
    rdbchecksum yes
    dbfilename dump.rdb
    dir /data
```

## File: k8s/network-policy.yaml

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: agentx-api-network-policy
  namespace: agentx
  labels:
    app: agentx
    component: network-policy
spec:
  podSelector:
    matchLabels:
      app: agentx
      component: api
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow ingress from nginx-ingress controller
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8000
  egress:
    # Allow DNS resolution
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
        - podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    # Allow connection to PostgreSQL
    - to:
        - podSelector:
            matchLabels:
              app: postgres
      ports:
        - protocol: TCP
          port: 5432
    # Allow connection to Redis
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - protocol: TCP
          port: 6379
    # Allow HTTPS egress (for external APIs like Anthropic)
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-network-policy
  namespace: agentx
  labels:
    app: postgres
    component: network-policy
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Only allow ingress from API pods
    - from:
        - podSelector:
            matchLabels:
              app: agentx
              component: api
      ports:
        - protocol: TCP
          port: 5432
  egress:
    # Allow DNS resolution
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
        - podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: redis-network-policy
  namespace: agentx
  labels:
    app: redis
    component: network-policy
spec:
  podSelector:
    matchLabels:
      app: redis
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Only allow ingress from API pods
    - from:
        - podSelector:
            matchLabels:
              app: agentx
              component: api
      ports:
        - protocol: TCP
          port: 6379
  egress:
    # Allow DNS resolution
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
        - podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
```

## File: k8s/pdb.yaml

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: agentx-api-pdb
  namespace: agentx
  labels:
    app: agentx
    component: api
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: agentx
      component: api
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-pdb
  namespace: agentx
  labels:
    app: postgres
spec:
  maxUnavailable: 0
  selector:
    matchLabels:
      app: postgres
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: redis-pdb
  namespace: agentx
  labels:
    app: redis
spec:
  maxUnavailable: 0
  selector:
    matchLabels:
      app: redis
```

## File: k8s/kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: agentx

resources:
  - namespace.yaml
  - configmap.yaml
  - secrets.yaml
  - api-deployment.yaml
  - api-service.yaml
  - api-ingress.yaml
  - hpa.yaml
  - postgres-statefulset.yaml
  - redis-statefulset.yaml
  - network-policy.yaml
  - pdb.yaml

commonLabels:
  app.kubernetes.io/name: agentx
  app.kubernetes.io/managed-by: kustomize

images:
  - name: ghcr.io/agentx/api
    newTag: latest
```