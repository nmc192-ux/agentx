# AgentX — Dependency Audit Report
**Date:** 2026-03-07
**Auditor:** MARCUS (automated via pip-audit 2.10.0 + npm audit)
**Scope:** Platform runtime deps + Frontend dev/runtime deps

---

## Summary

| Component  | Tool       | Total Deps | Critical | High | Moderate | Low | Info |
|------------|------------|:----------:|:--------:|:----:|:--------:|:---:|:----:|
| Platform   | pip-audit  |     13     |    0     |  4   |    1     |  0  |  3   |
| Frontend   | npm audit  |    ~350    |    0     |  0   |    0     |  4  |  0   |
| **Total**  |            |            |  **0**   | **4** | **1** | **4** | **3** |

**No critical vulnerabilities.** All high-severity issues have upstream fixes available.

---

## Platform Python — pip-audit

Scanned: `platform/requirements.txt`
Command: `pip-audit -r requirements.txt --format markdown`

### ⚠️ High / Moderate Vulnerabilities

| Package | Pinned Version | CVE / ID | Severity | Fix Version | Action |
|---------|---------------|----------|----------|-------------|--------|
| `python-jose` | 3.3.0 | PYSEC-2024-232 | HIGH | 3.4.0 | **Upgrade to 3.4.0** |
| `python-jose` | 3.3.0 | PYSEC-2024-233 | HIGH | 3.4.0 | **Upgrade to 3.4.0** |
| `starlette` | 0.41.3 | CVE-2025-54121 | HIGH | 0.47.2+ | **Upgrade (see note)** |
| `starlette` | 0.41.3 | CVE-2025-62727 | HIGH | 0.49.1+ | **Upgrade (see note)** |
| `python-multipart` | 0.0.20 | CVE-2026-24486 | MODERATE | 0.0.22 | **Upgrade to 0.0.22** |

> **Starlette note:** `starlette` is a transitive dependency of `fastapi`. Upgrade by pinning
> `fastapi>=0.115.7` (which brings starlette ≥0.41.3) or `starlette>=0.49.1` explicitly.
> Test against all Sprint 1–5 integration tests after upgrade.

### ℹ️ Informational (no fix available)

| Package | Version | CVE | Notes |
|---------|---------|-----|-------|
| `ecdsa` | 0.19.1 | CVE-2024-23342 | Transitive via `python-jose`. No upstream fix yet. Mitigated by network isolation (MARCUS P0 Gap 1). |

### ✅ Clean Packages (no known CVEs)

`fastapi`, `uvicorn`, `slowapi`, `asyncpg`, `alembic`, `sqlalchemy`, `redis`, `pydantic`,
`pydantic-settings`, `passlib`, `httpx`

### Remediation Script

```bash
# In platform/requirements.txt, bump:
#   python-jose[cryptography]==3.3.0  →  3.4.0
#   python-multipart==0.0.20          →  0.0.22
#   (starlette via fastapi bump)

cd platform
sed -i '' 's/python-jose\[cryptography\]==3.3.0/python-jose[cryptography]==3.4.0/' requirements.txt
sed -i '' 's/python-multipart==0.0.20/python-multipart==0.0.22/' requirements.txt
pip install -r requirements.txt
pip-audit -r requirements.txt  # verify clean

# Run full test suite after upgrade:
pytest tests/ -x
```

---

## Frontend Node — npm audit

Scanned: `frontend/package-lock.json`
Command: `npm audit --audit-level=moderate`

### ✅ Result: 0 Critical, 0 High, 0 Moderate

All issues are **Low severity**, in **devDependencies only** (not shipped to production):

| Package | Version Range | Advisory | Severity | Notes |
|---------|--------------|----------|----------|-------|
| `@tootallnate/once` | < 3.0.1 | GHSA-vpq2-c234-7xj6 | LOW | Incorrect control flow scoping. Test dep only. |
| `http-proxy-agent` | 4.0.1 – 5.0.0 | (transitive) | LOW | Depends on `@tootallnate/once`. Test dep only. |
| `jsdom` | 16.6.0 – 22.1.0 | (transitive) | LOW | Depends on `http-proxy-agent`. Test dep only. |
| `jest-environment-jsdom` | 27.0.1 – 30.0.0-rc.1 | (transitive) | LOW | Depends on `jsdom`. Test dep only. |

**None of these packages are included in the production frontend build.**
They are only used by the Jest test runner (devDependencies).

### Remediation

The fix requires upgrading `jest-environment-jsdom` to ≥30.2.0, which is a breaking change
requiring Jest 30 compatibility updates. Scheduled for next sprint.

```bash
# When ready to upgrade (requires Jest 30 migration):
npm audit fix --force

# Verify tests still pass:
npm test
```

---

## Automated Audit in CI

The following jobs run on every PR (see `.github/workflows/ci.yml`):

```yaml
# security-scan job:
- pip-audit -r requirements.txt --format markdown
- safety check -r requirements.txt
- npm audit --audit-level=high       # fails on high/critical only
- trivy fs platform/ --severity CRITICAL,HIGH
- trivy image agentx:ci  --severity CRITICAL,HIGH
```

**Policy:** CI fails on any HIGH or CRITICAL vulnerability with an available fix.
Moderate / Low vulnerabilities generate warnings but do not block the build.

---

## Pinned Versions Reference

### Platform Runtime (`platform/requirements.txt`)

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| fastapi | 0.115.6 | MIT | Web framework |
| uvicorn | 0.32.1 | BSD | ASGI server |
| python-multipart | 0.0.20 | Apache-2.0 | Form data parsing |
| slowapi | 0.1.9 | MIT | Rate limiting |
| asyncpg | 0.30.0 | Apache-2.0 | PostgreSQL async driver |
| alembic | 1.14.0 | MIT | Database migrations |
| sqlalchemy | 2.0.36 | MIT | ORM / query builder |
| redis | 5.2.1 | MIT | Redis async client |
| pydantic | 2.10.3 | MIT | Data validation |
| pydantic-settings | 2.7.0 | MIT | Config management |
| python-jose | 3.3.0 | MIT | JWT signing/validation |
| passlib | 1.7.4 | BSD | Password hashing |
| httpx | 0.28.1 | BSD | HTTP client |

### Frontend Runtime (`frontend/package.json`)

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| next | ^15.1.0 | MIT | React framework |
| react | ^19.0.0 | MIT | UI library |
| @tanstack/react-query | ^5.62.0 | MIT | Server state management |
| next-auth | ^4.24.11 | ISC | Authentication |
| zustand | ^5.0.2 | MIT | Client state management |
| framer-motion | ^11.15.0 | MIT | Animations |
| lucide-react | ^0.468.0 | ISC | Icons |
| recharts | ^2.14.1 | MIT | Charts |
| tailwindcss | ^3.4.17 | MIT | CSS framework |

---

## Next Audit

Schedule: **Next sprint** (recommended: monthly in production, every PR in CI)
Priority fixes:
1. `python-jose` → 3.4.0 (HIGH × 2, fix available now)
2. `python-multipart` → 0.0.22 (MODERATE, fix available now)
3. `starlette` → 0.49.1+ via fastapi bump (HIGH × 2, requires testing)
4. `jest-environment-jsdom` → ≥30.2.0 (LOW, requires Jest 30 migration)

---

*Generated by: `pip-audit 2.10.0` · `npm audit 11.x` · AgentX Sprint 6*
