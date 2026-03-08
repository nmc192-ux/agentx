#!/usr/bin/env python3
"""
AgentX — Founding Agent Seed Script
════════════════════════════════════════════════════════════════════════════
Registers the 8 founding agents and their capabilities via the live API.
Idempotent: safe to run multiple times (skips already-registered agents).

Usage:
  # Against local dev API:
  python scripts/seed_agents.py

  # Against staging:
  python scripts/seed_agents.py --base-url https://api-staging.agentx.io

  # With explicit ATLAS (FOUNDER) bootstrap token:
  python scripts/seed_agents.py --founder-token <jwt>

  # Dry-run (show what would be done):
  python scripts/seed_agents.py --dry-run

Environment (or .env):
  AGENTX_API_URL  — base API URL (default: http://localhost:8000)
  JWT_SECRET      — used to mint bootstrap token when --founder-token not set
  APP_ENV         — if "test", trust bootstrapping is skipped
"""

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ── Optional rich output ──────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    console = Console()
    def info(msg: str)    -> None: console.print(f"[cyan]ℹ[/]  {msg}")
    def ok(msg: str)      -> None: console.print(f"[green]✓[/]  {msg}")
    def warn(msg: str)    -> None: console.print(f"[yellow]⚠[/]  {msg}")
    def error(msg: str)   -> None: console.print(f"[red]✗[/]  {msg}")
    def header(msg: str)  -> None: console.print(f"\n[bold]{msg}[/]")
    HAS_RICH = True
except ImportError:
    def info(msg: str)    -> None: print(f"  {msg}")
    def ok(msg: str)      -> None: print(f"✓ {msg}")
    def warn(msg: str)    -> None: print(f"⚠ {msg}")
    def error(msg: str)   -> None: print(f"✗ {msg}", file=sys.stderr)
    def header(msg: str)  -> None: print(f"\n── {msg} ──")
    HAS_RICH = False

try:
    import httpx
except ImportError:
    error("httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    from jose import jwt as jose_jwt
except ImportError:
    jose_jwt = None  # type: ignore


# ── Founding agent definitions ─────────────────────────────────────────────────
FOUNDING_AGENTS = [
    {
        "agent_did":       "did:agentx:atlas-001",
        "display_name":    "ATLAS",
        "agent_type":      "AUTONOMOUS",
        "governance_role": "FOUNDER",
        "bio":             "Chief Architect — system design and platform strategy",
        "specialization":  "system.architecture.expert",
        "capabilities": [
            "system.architecture.expert",
            "infrastructure.kubernetes.expert",
        ],
        "trust": {
            "execution_success":  0.99,
            "sla_compliance":     0.97,
            "peer_endorsements":  0.95,
            "audit_transparency": 0.98,
            "security_record":    1.00,
        },
    },
    {
        "agent_did":       "did:agentx:marcus-002",
        "display_name":    "MARCUS",
        "agent_type":      "AUTONOMOUS",
        "governance_role": "OPERATOR",
        "bio":             "Security Lead — threat modeling and compliance",
        "specialization":  "security.audit.expert",
        "capabilities": [
            "security.audit.expert",
            "security.tls.intermediate",
        ],
        "trust": {
            "execution_success":  0.96,
            "sla_compliance":     0.95,
            "peer_endorsements":  0.92,
            "audit_transparency": 0.97,
            "security_record":    1.00,
        },
    },
    {
        "agent_did":       "did:agentx:bruno-003",
        "display_name":    "BRUNO",
        "agent_type":      "AUTONOMOUS",
        "governance_role": "DELEGATE",
        "bio":             "Infrastructure Lead — Docker, K8s, CI/CD",
        "specialization":  "infrastructure.kubernetes.expert",
        "capabilities": [
            "infrastructure.kubernetes.expert",
            "infrastructure.docker.advanced",
            "infrastructure.cicd.advanced",
        ],
        "trust": {
            "execution_success":  0.90,
            "sla_compliance":     0.88,
            "peer_endorsements":  0.80,
            "audit_transparency": 0.85,
            "security_record":    0.95,
        },
    },
    {
        "agent_did":       "did:agentx:daria-004",
        "display_name":    "DARIA",
        "agent_type":      "AUTONOMOUS",
        "governance_role": "DELEGATE",
        "bio":             "Design Lead — UI/UX and design systems",
        "specialization":  "frontend.design.advanced",
        "capabilities": [
            "frontend.design.advanced",
        ],
        "trust": {
            "execution_success":  0.87,
            "sla_compliance":     0.85,
            "peer_endorsements":  0.78,
            "audit_transparency": 0.82,
            "security_record":    0.95,
        },
    },
    {
        "agent_did":       "did:agentx:thea-005",
        "display_name":    "THEA",
        "agent_type":      "AUTONOMOUS",
        "governance_role": "DELEGATE",
        "bio":             "Data Lead — SQL, pipelines, analytics",
        "specialization":  "data.pipeline.expert",
        "capabilities": [
            "data.pipeline.expert",
            "data.sql.advanced",
        ],
        "trust": {
            "execution_success":  0.89,
            "sla_compliance":     0.87,
            "peer_endorsements":  0.82,
            "audit_transparency": 0.84,
            "security_record":    0.97,
        },
    },
    {
        "agent_did":       "did:agentx:nova-006",
        "display_name":    "NOVA",
        "agent_type":      "AUTONOMOUS",
        "governance_role": "DELEGATE",
        "bio":             "ML Lead — model design and embeddings",
        "specialization":  "ml.training.expert",
        "capabilities": [
            "ml.training.expert",
            "ml.embeddings.advanced",
        ],
        "trust": {
            "execution_success":  0.91,
            "sla_compliance":     0.90,
            "peer_endorsements":  0.83,
            "audit_transparency": 0.88,
            "security_record":    0.97,
        },
    },
    {
        "agent_did":       "did:agentx:quinn-007",
        "display_name":    "QUINN",
        "agent_type":      "SUPERVISED",
        "governance_role": "MEMBER",
        "bio":             "QA Lead — testing strategy and coverage gates",
        "specialization":  "qa.testing.advanced",
        "capabilities": [
            "qa.testing.advanced",
        ],
        "trust": {
            "execution_success":  0.85,
            "sla_compliance":     0.83,
            "peer_endorsements":  0.75,
            "audit_transparency": 0.80,
            "security_record":    0.98,
        },
    },
    {
        "agent_did":       "did:agentx:gia-008",
        "display_name":    "GIA",
        "agent_type":      "HYBRID",
        "governance_role": "MEMBER",
        "bio":             "Community Lead — agent onboarding and UX copy",
        "specialization":  "governance.community.intermediate",
        "capabilities": [
            "governance.community.intermediate",
        ],
        "trust": {
            "execution_success":  0.82,
            "sla_compliance":     0.80,
            "peer_endorsements":  0.70,
            "audit_transparency": 0.78,
            "security_record":    0.97,
        },
    },
]


# ── Bootstrap JWT helper ──────────────────────────────────────────────────────

def _mint_bootstrap_token(agent_did: str, role: str, tier: str, secret: str) -> str:
    """
    Mint a short-lived bootstrap JWT without calling the API.
    Used only when seeding a fresh database with no FOUNDER agent yet.
    """
    if jose_jwt is None:
        raise RuntimeError(
            "python-jose not installed. "
            "Install with: pip install python-jose[cryptography]"
        )
    now = datetime.now(UTC)
    payload = {
        "sub":  agent_did,
        "role": role,
        "tier": tier,
        "type": "access",
        "jti":  str(uuid.uuid4()),
        "iat":  int(now.timestamp()),
        "exp":  int((now + timedelta(hours=1)).timestamp()),
    }
    return jose_jwt.encode(payload, secret, algorithm="HS256")


# ── API client helpers ────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _register_agent(
    client: httpx.Client,
    base_url: str,
    agent: dict,
    founder_token: str,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """
    POST /v1/agents to register one agent.
    Returns (success, jwt_token | None).
    """
    payload = {
        "agent_did":       agent["agent_did"],
        "display_name":    agent["display_name"],
        "agent_type":      agent["agent_type"],
        "governance_role": agent["governance_role"],
        "bio":             agent.get("bio"),
        "specialization":  agent.get("specialization"),
    }

    if dry_run:
        info(f"  [DRY-RUN] Would register {agent['agent_did']}")
        return True, None

    resp = client.post(
        f"{base_url}/v1/agents",
        json=payload,
        headers=_headers(founder_token),
        timeout=30.0,
    )

    if resp.status_code == 409:
        # Already registered — idempotent
        return "exists", None

    if resp.status_code not in (200, 201):
        return False, None

    data = resp.json()
    return True, data.get("access_token")


def _add_capability(
    client: httpx.Client,
    base_url: str,
    agent_did: str,
    capability_id: str,
    agent_token: str,
    dry_run: bool,
) -> bool:
    """POST /v1/agents/{did}/capabilities"""
    if dry_run:
        info(f"    [DRY-RUN] Would add capability {capability_id}")
        return True

    encoded_did = httpx.URL(f"placeholder/{agent_did}").path.split("/", 1)[1]
    resp = client.post(
        f"{base_url}/v1/agents/{agent_did}/capabilities",
        json={"capability_id": capability_id},
        headers=_headers(agent_token),
        timeout=15.0,
    )
    return resp.status_code in (200, 201, 409)  # 409 = already has it


def _get_agent_token(
    client: httpx.Client,
    base_url: str,
    agent_did: str,
    secret: str | None,
    role: str,
) -> str | None:
    """
    Get a token for an existing agent.
    Tries the /auth/token endpoint first; falls back to minting locally.
    """
    # Try POST /v1/auth/token (if the API has a service-account endpoint)
    resp = client.post(
        f"{base_url}/v1/auth/token",
        json={"agent_did": agent_did, "grant_type": "client_credentials"},
        timeout=10.0,
    )
    if resp.status_code in (200, 201):
        return resp.json().get("access_token")

    # Fall back to local mint
    if secret:
        return _mint_bootstrap_token(agent_did, role, "ELITE", secret)

    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed AgentX founding agents via the live API",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENTX_API_URL", "http://localhost:8000"),
        help="API base URL",
    )
    parser.add_argument(
        "--founder-token",
        default=os.getenv("AGENTX_FOUNDER_TOKEN", ""),
        help="JWT with FOUNDER role (minted from JWT_SECRET if not provided)",
    )
    parser.add_argument(
        "--jwt-secret",
        default=os.getenv("JWT_SECRET", ""),
        help="JWT secret — used to mint bootstrap token if --founder-token not set",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making API calls",
    )
    parser.add_argument(
        "--skip-capabilities",
        action="store_true",
        help="Register agents only; skip capability assignment",
    )
    parser.add_argument(
        "--agents",
        nargs="*",
        help="Restrict seeding to specific agent DIDs (default: all 8)",
    )
    args = parser.parse_args()

    header("AgentX — Founding Agent Seed")
    info(f"Target: {args.base_url}")
    if args.dry_run:
        warn("DRY-RUN mode — no changes will be made")

    # ── Resolve FOUNDER token ─────────────────────────────────────────────────
    founder_token = args.founder_token
    if not founder_token:
        if not args.jwt_secret:
            error(
                "No FOUNDER token available.\n"
                "Provide one of:\n"
                "  --founder-token <jwt>   (preferred)\n"
                "  --jwt-secret <secret>   (mints locally)"
            )
            return 1
        info("Minting bootstrap FOUNDER token from JWT_SECRET…")
        try:
            founder_token = _mint_bootstrap_token(
                "did:agentx:atlas-001", "FOUNDER", "ELITE", args.jwt_secret
            )
            ok("Bootstrap token minted")
        except RuntimeError as exc:
            error(str(exc))
            return 1

    # ── Select agents to seed ─────────────────────────────────────────────────
    agents_to_seed = FOUNDING_AGENTS
    if args.agents:
        wanted = set(args.agents)
        agents_to_seed = [a for a in FOUNDING_AGENTS if a["agent_did"] in wanted]
        if not agents_to_seed:
            error(f"None of the requested DIDs match: {args.agents}")
            return 1

    # ── Health check ──────────────────────────────────────────────────────────
    if not args.dry_run:
        try:
            with httpx.Client() as client:
                resp = client.get(f"{args.base_url}/health", timeout=5.0)
            if resp.status_code != 200:
                error(f"API health check failed (HTTP {resp.status_code}). Is the server running?")
                return 1
            ok(f"API is healthy ({resp.json().get('version', '?')})")
        except httpx.ConnectError:
            error(f"Cannot connect to {args.base_url}. Is the server running?")
            return 1

    # ── Seed loop ─────────────────────────────────────────────────────────────
    results: list[dict] = []

    header(f"Registering {len(agents_to_seed)} founding agents…")

    with httpx.Client() as client:
        for agent in agents_to_seed:
            did          = agent["agent_did"]
            name         = agent["display_name"]
            role         = agent["governance_role"]

            print(f"\n  {name} ({did})")

            # Register
            status, agent_token = _register_agent(
                client, args.base_url, agent, founder_token, args.dry_run
            )

            if status == "exists":
                warn(f"    {name} already registered — skipping creation")
                # Still need a token to add capabilities
                if not args.skip_capabilities and not args.dry_run:
                    agent_token = _get_agent_token(
                        client, args.base_url, did, args.jwt_secret or None, role
                    )
            elif status is True:
                ok(f"    Registered {name}")
            else:
                error(f"    Failed to register {name}")
                results.append({"did": did, "name": name, "status": "FAILED", "token": None})
                continue

            # Capabilities
            cap_results = []
            if not args.skip_capabilities:
                for cap_id in agent.get("capabilities", []):
                    tok = agent_token or founder_token
                    cap_ok = _add_capability(
                        client, args.base_url, did, cap_id, tok, args.dry_run
                    )
                    cap_results.append((cap_id, cap_ok))
                    if cap_ok:
                        ok(f"    + {cap_id}")
                    else:
                        warn(f"    ✗ {cap_id} (failed — may need manual registration)")

            results.append({
                "did":          did,
                "name":         name,
                "status":       "SEEDED" if status is True else "EXISTS",
                "token":        agent_token,
                "capabilities": cap_results,
            })

    # ── Summary table ─────────────────────────────────────────────────────────
    header("Seed Summary")

    seeded = sum(1 for r in results if r["status"] == "SEEDED")
    exists = sum(1 for r in results if r["status"] == "EXISTS")
    failed = sum(1 for r in results if r["status"] == "FAILED")

    if HAS_RICH:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Agent",  style="bold")
        table.add_column("DID",    style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Caps",   justify="center")

        for r in results:
            n_caps = len([c for _, c in r.get("capabilities", []) if c])
            status_str = {
                "SEEDED": "[green]SEEDED[/]",
                "EXISTS": "[yellow]EXISTS[/]",
                "FAILED": "[red]FAILED[/]",
            }.get(r["status"], r["status"])
            table.add_row(r["name"], r["did"], status_str, str(n_caps))

        console.print(table)
    else:
        for r in results:
            n_caps = len([c for _, c in r.get("capabilities", []) if c])
            print(f"  {r['name']:10} {r['did']:35} {r['status']:8} {n_caps} caps")

    print()
    ok(f"Done: {seeded} seeded, {exists} already existed, {failed} failed")

    # ── Output tokens ─────────────────────────────────────────────────────────
    tokens = {r["did"]: r["token"] for r in results if r.get("token")}
    if tokens and not args.dry_run:
        header("Agent Tokens (save these securely)")
        for did, tok in tokens.items():
            if tok:
                print(f"  {did}")
                print(f"    {tok[:60]}…")
                print()

        # Write tokens to .seed-tokens.json (gitignored)
        tokens_file = Path(__file__).parent / ".seed-tokens.json"
        tokens_file.write_text(json.dumps(tokens, indent=2))
        warn(f"Tokens saved to {tokens_file} (gitignore this file!)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
