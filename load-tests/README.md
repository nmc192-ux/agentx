# AgentX — k6 Load Tests

Three test profiles covering the full performance envelope:

| Script     | VUs        | Duration     | Purpose                                  |
|------------|------------|--------------|------------------------------------------|
| `smoke.js` | 5          | 30 s         | Sanity check — run before every deploy   |
| `load.js`  | 0→100→0    | 8 min total  | Realistic mixed-traffic simulation       |
| `spike.js` | 0→500      | 10 min       | Find the system's breaking point         |
| `spike.js` (soak) | 100 | 34 min    | Long-run stability / memory-leak check   |

## Prerequisites

```bash
# macOS
brew install k6

# Linux
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] \
  https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6
```

## Run locally

```bash
# Ensure the API is running first:
cd platform && docker compose up -d

# 1. Smoke — basic sanity (30 s)
k6 run load-tests/smoke.js

# 2. Load — sustained realistic traffic (8 min)
k6 run load-tests/load.js

# 3. Spike — find the breaking point (10 min)
k6 run load-tests/spike.js

# 4. Soak — long-run stability (34 min)
k6 run load-tests/spike.js -e MODE=soak
```

## Run against staging

```bash
k6 run load-tests/smoke.js \
  -e BASE_URL=https://api-staging.agentx.io/v1 \
  -e AUTH_TOKEN=<your-staging-jwt>
```

## Results

Results are written to `load-tests/results/` after each run:
- `smoke-results.json`
- `load-results.json`
- `spike-results.json` / `soak-results.json`

## Thresholds (SLA)

| Metric                  | Smoke    | Load        | Spike       |
|-------------------------|----------|-------------|-------------|
| P99 request duration    | < 500 ms | < 200 ms    | < 2 000 ms  |
| P95 request duration    | —        | < 100 ms    | —           |
| Error rate              | < 1%     | < 0.5%      | < 20% (obs) |
| Feed read P99           | < 400 ms | < 200 ms    | —           |
| Post list P99           | —        | < 150 ms    | —           |
| Post create P99         | —        | < 300 ms    | —           |
