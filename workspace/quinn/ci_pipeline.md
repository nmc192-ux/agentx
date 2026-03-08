# Complete GitHub Actions CI/CD Pipeline for AgentX

## File: .github/workflows/ci.yml

```yaml
name: AgentX CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: "3.12"
  NODE_VERSION: "20"
  DOCKER_REGISTRY: ghcr.io
  IMAGE_NAME: agentx/platform

jobs:
  # ============================================================================
  # JOB 1: LINT
  # ============================================================================
  lint:
    name: Lint & Type Check
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install Python dependencies
        run: |
          pip install --upgrade pip
          pip install ruff mypy pytest
          pip install -r requirements.txt

      - name: Run Ruff linting
        run: |
          ruff check src/ tests/ --output-format=github
        continue-on-error: false

      - name: Run Ruff formatting check
        run: |
          ruff format --check src/ tests/

      - name: Run mypy type checking
        run: |
          mypy src/ --strict --ignore-missing-imports --no-error-summary
        continue-on-error: false

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'

      - name: Install Node dependencies
        run: |
          npm ci
        working-directory: frontend

      - name: Run ESLint (TypeScript)
        run: |
          npm run lint
        working-directory: frontend

      - name: TypeScript type check
        run: |
          npm run type-check
        working-directory: frontend

  # ============================================================================
  # JOB 2: UNIT TESTS
  # ============================================================================
  test-unit:
    name: Unit Tests (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    needs: lint
    
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
      fail-fast: false

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pytest pytest-asyncio pytest-cov hypothesis faker factory-boy
          pip install -r requirements.txt

      - name: Run unit tests with coverage
        run: |
          pytest tests/ \
            -m "not integration" \
            --cov=src \
            --cov-report=xml \
            --cov-report=term \
            --cov-fail-under=80 \
            --maxfail=5 \
            -v

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          token: ${{ secrets.CODECOV_TOKEN }}
          files: ./coverage.xml
          flags: unittests
          name: codecov-umbrella
          fail_ci_if_error: false

      - name: Generate coverage badge
        if: matrix.python-version == '3.12'
        run: |
          pip install coverage-badge
          coverage-badge -o coverage.svg -f

      - name: Upload coverage badge
        if: matrix.python-version == '3.12'
        uses: actions/upload-artifact@v4
        with:
          name: coverage-badge
          path: coverage.svg

  # ============================================================================
  # JOB 3: INTEGRATION TESTS
  # ============================================================================
  test-integration:
    name: Integration Tests
    runs-on: ubuntu-latest
    needs: test-unit

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: agentx_test
          POSTGRES_USER: agentx
          POSTGRES_PASSWORD: agentx_test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    env:
      DATABASE_URL: postgresql+asyncpg://agentx:agentx_test_password@localhost:5432/agentx_test
      REDIS_URL: redis://localhost:6379

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pytest pytest-asyncio pytest-cov alembic asyncpg redis
          pip install -r requirements.txt

      - name: Wait for PostgreSQL
        run: |
          until pg_isready -h localhost -p 5432 -U agentx; do
            echo "Waiting for PostgreSQL..."
            sleep 2
          done

      - name: Run Alembic migrations
        run: |
          alembic upgrade head

      - name: Run integration tests
        run: |
          pytest tests/ \
            -m "integration" \
            --cov=src \
            --cov-report=xml \
            --cov-report=term \
            -v \
            --tb=short

      - name: Upload integration test coverage
        uses: codecov/codecov-action@v4
        with:
          token: ${{ secrets.CODECOV_TOKEN }}
          files: ./coverage.xml
          flags: integration
          fail_ci_if_error: false

  # ============================================================================
  # JOB 4: SCHEMA VALIDATION & CONTRACT TESTING
  # ============================================================================
  test-schema-validation:
    name: Schema Validation & Contract Tests
    runs-on: ubuntu-latest
    needs: test-unit

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install jsonschema schemathesis pytest
          pip install -r requirements.txt

      - name: Validate JSON Schemas against meta-schema
        run: |
          python -c "
          import json
          import sys
          from pathlib import Path
          from jsonschema import Draft202012Validator, ValidationError
          
          schema_dir = Path('workspace/shared')
          failed = []
          
          for schema_file in schema_dir.glob('*.json'):
              print(f'Validating {schema_file.name}...')
              with open(schema_file) as f:
                  schema = json.load(f)
              
              try:
                  Draft202012Validator.check_schema(schema)
                  print(f'  ✓ {schema_file.name} is valid')
              except ValidationError as e:
                  print(f'  ✗ {schema_file.name} is invalid: {e.message}')
                  failed.append(schema_file.name)
          
          if failed:
              print(f'\n❌ {len(failed)} schema(s) failed validation')
              sys.exit(1)
          else:
              print(f'\n✅ All schemas valid')
          "

      - name: Start test server for contract testing
        run: |
          pip install uvicorn
          uvicorn src.api.app:app --host 0.0.0.0 --port 8000 &
          sleep 5
        env:
          DATABASE_URL: sqlite+aiosqlite:///:memory:
          REDIS_URL: redis://localhost:6379

      - name: Run Schemathesis contract tests
        run: |
          schemathesis run workspace/shared/agentx_api_v1.yaml \
            --base-url http://localhost:8000/v1 \
            --checks all \
            --hypothesis-max-examples=50 \
            --hypothesis-deadline=5000 \
            --report

      - name: Validate test fixtures against schemas
        run: |
          pytest tests/test_agent_identity_schema.py \
            tests/test_post_synthesis_schema.py \
            -v

  # ============================================================================
  # JOB 5: SECURITY SCANNING
  # ============================================================================
  security-scan:
    name: Security Scanning
    runs-on: ubuntu-latest
    needs: test-unit

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install security tools
        run: |
          pip install --upgrade pip
          pip install bandit safety
          pip install -r requirements.txt

      - name: Run Bandit security scanner
        run: |
          bandit -r src/ \
            -f json \
            -o bandit-report.json \
            --severity-level medium
        continue-on-error: true

      - name: Display Bandit results
        if: always()
        run: |
          if [ -f bandit-report.json ]; then
            cat bandit-report.json | python -m json.tool
          fi

      - name: Run Safety dependency scanner
        run: |
          safety check \
            --json \
            --output safety-report.json
        continue-on-error: true

      - name: Display Safety results
        if: always()
        run: |
          if [ -f safety-report.json ]; then
            cat safety-report.json | python -m json.tool
          fi

      - name: Upload security reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: security-reports
          path: |
            bandit-report.json
            safety-report.json

      - name: Build Docker image for Trivy scan
        run: |
          docker build -t agentx-security-scan:${{ github.sha }} .

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: agentx-security-scan:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'

      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: 'trivy-results.sarif'

  # ============================================================================
  # JOB 6: BUILD & PUSH DOCKER IMAGE
  # ============================================================================
  build-docker:
    name: Build & Push Docker Image
    runs-on: ubuntu-latest
    needs: [test-integration, security-scan]
    if: github.event_name == 'push'

    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.DOCKER_REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.DOCKER_REGISTRY }}/${{ github.repository }}
          tags: |
            type=ref,event=branch
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            BUILD_DATE=${{ github.event.head_commit.timestamp }}
            VCS_REF=${{ github.sha }}
            VERSION=${{ steps.meta.outputs.version }}

      - name: Generate image digest
        run: |
          echo "Image pushed: ${{ steps.meta.outputs.tags }}"

  # ============================================================================
  # JOB 7: DEPLOY TO STAGING
  # ============================================================================
  deploy-staging:
    name: Deploy to Staging
    runs-on: ubuntu-latest
    needs: build-docker
    if: github.ref == 'refs/heads/main'
    environment:
      name: staging
      url: https://staging.agentx.ai

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up kubectl
        uses: azure/setup-kubectl@v4
        with:
          version: 'latest'

      - name: Configure kubectl
        run: |
          mkdir -p ~/.kube
          echo "${{ secrets.KUBE_CONFIG_STAGING }}" | base64 -d > ~/.kube/config

      - name: Update deployment image
        run: |
          kubectl set image deployment/agentx-api \
            agentx-api=${{ env.DOCKER_REGISTRY }}/${{ github.repository }}:main-${{ github.sha }} \
            --namespace=staging

      - name: Apply Kubernetes manifests
        run: |
          kubectl apply -f k8s/staging/ --namespace=staging

      - name: Wait for rollout
        run: |
          kubectl rollout status deployment/agentx-api \
            --namespace=staging \
            --timeout=5m

      - name: Verify deployment
        run: |
          kubectl get pods -n staging -l app=agentx-api
          kubectl get services -n staging -l app=agentx-api

      - name: Run smoke tests against staging
        run: |
          pip install httpx pytest
          pytest tests/smoke/ \
            --base-url=https://staging.agentx.ai \
            -v \
            --tb=short

      - name: Notify deployment success
        if: success()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "✅ AgentX deployed to staging successfully",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Deployment Successful* 🚀\n• Environment: Staging\n• Commit: `${{ github.sha }}`\n• Author: ${{ github.actor }}\n• URL: https://staging.agentx.ai"
                  }
                }
              ]
            }'

      - name: Notify deployment failure
        if: failure()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "❌ AgentX staging deployment failed",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Deployment Failed* ⚠️\n• Environment: Staging\n• Commit: `${{ github.sha }}`\n• Author: ${{ github.actor }}\n• View logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }'
```

## File: .github/workflows/nightly.yml

```yaml
name: AgentX Nightly Quality Checks

on:
  schedule:
    # Run every day at 2 AM UTC
    - cron: '0 2 * * *'
  workflow_dispatch: # Allow manual trigger

env:
  PYTHON_VERSION: "3.12"
  STAGING_URL: "https://staging.agentx.ai"

jobs:
  # ============================================================================
  # JOB 1: LOAD TESTING
  # ============================================================================
  load-test:
    name: k6 Load Test (Staging)
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Install k6
        run: |
          sudo gpg -k
          sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
          echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
          sudo apt-get update
          sudo apt-get install k6

      - name: Run k6 smoke test
        run: |
          k6 run load-tests/smoke.js \
            --env BASE_URL=${{ env.STAGING_URL }}/v1 \
            --out json=smoke-results.json

      - name: Upload k6 results
        uses: actions/upload-artifact@v4
        with:
          name: k6-smoke-results
          path: smoke-results.json

      - name: Check load test thresholds
        run: |
          python -c "
          import json
          import sys
          
          with open('smoke-results.json') as f:
              for line in f:
                  data = json.loads(line)
                  if data['type'] == 'Point' and data['metric'] == 'http_req_duration':
                      p99 = data['data']['tags']['p99']
                      if float(p99) > 500:
                          print(f'❌ P99 latency exceeded threshold: {p99}ms > 500ms')
                          sys.exit(1)
          
          print('✅ All load test thresholds passed')
          "

      - name: Notify on load test failure
        if: failure()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "⚠️ AgentX nightly load test failed",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Nightly Load Test Failed*\n• P99 latency exceeded 500ms threshold\n• Check staging performance\n• View logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }'

  # ============================================================================
  # JOB 2: TRUST SCORE DRIFT CHECK
  # ============================================================================
  trust-score-drift:
    name: Trust Score Drift Test
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: agentx_test
          POSTGRES_USER: agentx
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    env:
      DATABASE_URL: postgresql+asyncpg://agentx:test_password@localhost:5432/agentx_test

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pytest pytest-asyncio
          pip install -r requirements.txt

      - name: Run Alembic migrations
        run: |
          alembic upgrade head

      - name: Run concurrent trust score recalculation test
        run: |
          pytest tests/test_sla_monitoring.py::test_concurrent_recalculations_no_drift \
            -v \
            --tb=short \
            --maxfail=1

      - name: Notify on drift detection
        if: failure()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "🚨 Trust score drift detected in nightly check",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Trust Score Drift Detected*\n• Concurrent recalculations exceeded 0.01 drift threshold\n• Investigate trust score calculation consistency\n• View logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }'

  # ============================================================================
  # JOB 3: FULL SCHEMATHESIS FUZZING
  # ============================================================================
  schema-fuzzing:
    name: Full Schemathesis Fuzzing
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install schemathesis
          pip install -r requirements.txt

      - name: Run full Schemathesis fuzzing against staging
        run: |
          schemathesis run workspace/shared/agentx_api_v1.yaml \
            --base-url ${{ env.STAGING_URL }}/v1 \
            --checks all \
            --hypothesis-max-examples=1000 \
            --hypothesis-deadline=10000 \
            --hypothesis-derandomize \
            --workers=4 \
            --report \
            --junit-xml=schemathesis-report.xml
        continue-on-error: true

      - name: Upload fuzzing results
        uses: actions/upload-artifact@v4
        with:
          name: schemathesis-fuzzing-results
          path: schemathesis-report.xml

      - name: Check for failures
        run: |
          if grep -q 'failures="[1-9]' schemathesis-report.xml; then
            echo "❌ Schemathesis fuzzing found API contract violations"
            exit 1
          fi
          echo "✅ No API contract violations found"

      - name: Notify on fuzzing failures
        if: failure()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "🐛 Schemathesis fuzzing found API issues",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*API Contract Violations Detected*\n• Full fuzzing run found inconsistencies\n• Review schemathesis report\n• View logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }'

  # ============================================================================
  # JOB 4: SLA BREACH RATE CHECK
  # ============================================================================
  sla-breach-check:
    name: SLA Breach Rate Check
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install httpx
          pip install -r requirements.txt

      - name: Check SLA breach rate
        run: |
          python -c "
          import httpx
          import sys
          
          response = httpx.get('${{ env.STAGING_URL }}/v1/health')
          data = response.json()
          
          sla_component = next((c for c in data['components'] if c['name'] == 'sla_monitoring'), None)
          
          if sla_component:
              breach_rate = float(sla_component['metadata']['breach_rate'].rstrip('%'))
              print(f'SLA breach rate: {breach_rate}%')
              
              if breach_rate > 2.0:
                  print(f'❌ SLA breach rate exceeds 2% threshold')
                  sys.exit(1)
              else:
                  print(f'✅ SLA breach rate within acceptable range')
          else:
              print('⚠️ Could not retrieve SLA monitoring status')
              sys.exit(1)
          "

      - name: Notify on high breach rate
        if: failure()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "⚠️ SLA breach rate exceeded 2% threshold",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*High SLA Breach Rate*\n• Breach rate >2% detected on staging\n• Review task assignments and deadlines\n• Check system performance"
                  }
                }
              ]
            }'

  # ============================================================================
  # FINAL: SUMMARY NOTIFICATION
  # ============================================================================
  notify-summary:
    name: Send Summary Notification
    runs-on: ubuntu-latest
    needs: [load-test, trust-score-drift, schema-fuzzing, sla-breach-check]
    if: always()

    steps:
      - name: Determine overall status
        id: status
        run: |
          if [ "${{ contains(needs.*.result, 'failure') }}" == "true" ]; then
            echo "status=failure" >> $GITHUB_OUTPUT
            echo "emoji=❌" >> $GITHUB_OUTPUT
          else
            echo "status=success" >> $GITHUB_OUTPUT
            echo "emoji=✅" >> $GITHUB_OUTPUT
          fi

      - name: Send summary notification
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK_URL }} \
            -H 'Content-Type: application/json' \
            -d '{
              "text": "${{ steps.status.outputs.emoji }} AgentX nightly quality checks completed",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Nightly Quality Checks Summary*\n• Load Test: ${{ needs.load-test.result }}\n• Trust Score Drift: ${{ needs.trust-score-drift.result }}\n• Schema Fuzzing: ${{ needs.schema-fuzzing.result }}\n• SLA Breach Rate: ${{ needs.sla-breach-check.result }}\n\n<${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}|View full report>"
                  }
                }
              ]
            }'
```

## File: .pre-commit-config.yaml

```yaml
# AgentX Pre-commit Hooks Configuration
# Install: pre-commit install
# Run manually: pre-commit run --all-files

repos:
  # ============================================================================
  # PYTHON: RUFF (LINTING & FORMATTING)
  # ============================================================================
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        name: Ruff Linting
        args: [--fix, --exit-non-zero-on-fix]
        types_or: [python, pyi]
      
      - id: ruff-format
        name: Ruff Formatting
        types_or: [python, pyi]

  # ============================================================================
  # PYTHON: MYPY (TYPE CHECKING)
  # ============================================================================
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        name: MyPy Type Checking
        args: [--strict, --ignore-missing-imports, --no-error-summary]
        additional_dependencies:
          - types-redis
          - types-jsonschema
          - sqlalchemy[mypy]
        files: ^src/
        exclude: ^tests/

  # ============================================================================
  # PYTHON: PYTEST (FAST UNIT TESTS)
  # ============================================================================
  - repo: local
    hooks:
      - id: pytest-fast
        name: PyTest (Fast Unit Tests)
        entry: pytest
        language: system
        args:
          - tests/
          - -m
          - "not integration and not slow"
          - --tb=short
          - --maxfail=3
          - -q
        pass_filenames: false
        timeout: 30

  # ============================================================================
  # JSON SCHEMA VALIDATION
  # ============================================================================
  - repo: local
    hooks:
      - id: validate-json-schemas
        name: Validate JSON Schemas
        entry: python
        language: system
        args:
          - -c
          - |
            import json
            import sys
            from pathlib import Path
            from jsonschema import Draft202012Validator, ValidationError
            
            schema_dir = Path('workspace/shared')
            failed = []
            
            for schema_file in schema_dir.glob('*.json'):
                with open(schema_file) as f:
                    try:
                        schema = json.load(f)
                        Draft202012Validator.check_schema(schema)
                    except (json.JSONDecodeError, ValidationError) as e:
                        print(f'❌ {schema_file.name}: {e}')
                        failed.append(schema_file.name)
            
            if failed:
                sys.exit(1)
        files: ^workspace/shared/.*\.json$
        pass_filenames: false

  # ============================================================================
  # SECRET DETECTION
  # ============================================================================
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        name: Detect Secrets
        args: ['--baseline', '.secrets.baseline']
        exclude: (^tests/|\.lock$|package-lock\.json$)

  # ============================================================================
  # GENERAL FILE CHECKS
  # ============================================================================
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
        name: Trim Trailing Whitespace
      
      - id: end-of-file-fixer
        name: Fix End of Files
      
      - id: check-yaml
        name: Check YAML Syntax
        args: [--safe]
      
      - id: check-json
        name: Check JSON Syntax
      
      - id: check-toml
        name: Check TOML Syntax
      
      - id: check-added-large-files
        name: Check for Large Files
        args: [--maxkb=1000]
      
      - id: check-merge-conflict
        name: Check for Merge Conflicts
      
      - id: check-case-conflict
        name: Check for Case Conflicts
      
      - id: mixed-line-ending
        name: Check Line Endings
        args: [--fix=lf]

  # ============================================================================
  # SQL MIGRATIONS CHECK
  # ============================================================================
  - repo: local
    hooks:
      - id: alembic-check
        name: Check Alembic Migrations
        entry: python
        language: system
        args:
          - -c
          - |
            import subprocess
            import sys
            
            result = subprocess.run(
                ['alembic', 'check'],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print('❌ Alembic migration check failed')
                print(result.stdout)
                print(result.stderr)
                sys.exit(1)
            
            print('✅ Alembic migrations are up to date')
        pass_filenames: false
        files: ^(alembic/|src/database/models\.py)

  # ============================================================================
  # DOCKER: HADOLINT (DOCKERFILE LINTING)
  # ============================================================================
  - repo: https://github.com/hadolint/hadolint
    rev: v2.12.0
    hooks:
      - id: hadolint-docker
        name: Lint Dockerfiles
        args: [--ignore, DL3008, --ignore, DL3009]

  # ============================================================================
  # MARKDOWN LINTING
  # ============================================================================
  - repo: https://github.com/igorshubovych/markdownlint-cli
    rev: v0.38.0
    hooks:
      - id: markdownlint
        name: Lint Markdown Files
        args: [--fix]

  # ============================================================================
  # COMMIT MESSAGE LINTING
  # ============================================================================
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v3.0.0
    hooks:
      - id: conventional-pre-commit
        name: Check Commit Message Format
        stages: [commit-msg]
        args: [--strict, --force-scope]

# Global configuration
default_language_version:
  python: python3.12

fail_fast: false
minimum_pre_commit_version: '3.0.0'
```

## File: .github/dependabot.yml

```yaml
# Dependabot configuration for automated dependency updates

version: 2
updates:
  # Python dependencies
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
    open-pull-requests-limit: 10
    reviewers:
      - "atlas-agent"
    labels:
      - "dependencies"
      - "python"
    commit-message:
      prefix: "chore(deps)"
      include: "scope"

  # GitHub Actions
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "github-actions"
    commit-message:
      prefix: "chore(ci)"

  # Docker base images
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "docker"
    commit-message:
      prefix: "chore(docker)"

  # NPM (frontend)
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
    open-pull-requests-limit: 10
    labels:
      - "dependencies"
      - "frontend"
    commit-message:
      prefix: "chore(deps)"
      include: "scope"
```

This completes the comprehensive CI/CD pipeline for AgentX with:
- Full lint, test, security scan, build, and deploy automation
- Nightly quality checks for load testing, trust score drift, API fuzzing, and SLA monitoring
- Pre-commit hooks for fast local validation
- Automated dependency updates via Dependabot