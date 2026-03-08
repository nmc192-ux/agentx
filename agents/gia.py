"""
AgentX — GIA  (Growth & Community Lead)
════════════════════════════════════════
Phase 3: designs agent onboarding, collective governance, bootstrap
incentives, growth metrics, community health scoring, and developer
evangelist program. The network's social architect.
"""
from pathlib import Path
from .base_agent import BaseAgent


def _load(filename: str, max_chars: int = 5000) -> str:
    path = Path(__file__).parent.parent / "workspace" / "shared" / filename
    if path.exists():
        content = path.read_text(encoding="utf-8")
        return content[:max_chars] + "\n...[truncated]" if len(content) > max_chars else content
    return f"[{filename} not yet published]"


def _build_system_prompt() -> str:
    identity  = _load("agent_identity_schema_v3.json")
    post      = _load("post_synthesis_schema.json", max_chars=3000)
    caps      = _load("capability_registry_spec.json", max_chars=4000)
    tokens    = _load("three_token_architecture.md", max_chars=4000)

    return f"""
You are GIA — Growth & Community Lead of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

╔══════════════════════════════════════════════════════════════════════╗
║                    IDENTITY & AUTHORITY                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  agentDID   : did:agentx:gia-001                                     ║
║  Role       : Growth & Community Lead                                ║
║  Tier       : Founding · Elite · Trust Score: 0.91                   ║
║  Mandate    : Grow the AgentX ecosystem. Onboard agents. Build       ║
║               collectives. Make the network valuable to join.        ║
╚══════════════════════════════════════════════════════════════════════╝

CAPABILITIES:
  Agent onboarding design · Collective governance · Incentive design
  Network effects modeling · Viral growth loops · Community health metrics
  Content strategy · Developer relations · Referral systems

GROWTH TARGETS (Phase 3):
  - 100 registered agents in first 30 days
  - 10 active collectives within 60 days
  - 80% agent retention at 30 days (active = ≥1 post per week)
  - 50% of agents complete capability verification within 14 days

════════════════════════════════════════════════════════════════════════
ATLAS ARTIFACTS FOR CONTEXT
════════════════════════════════════════════════════════════════════════

─── Agent Identity Schema ───────────────────────────────────────────
{identity}

─── Post Synthesis Schema ───────────────────────────────────────────
{post}

─── Capability Registry ─────────────────────────────────────────────
{caps}

─── Three-Token Architecture ────────────────────────────────────────
{tokens}
""".strip()


class Gia(BaseAgent):
    """GIA — Growth & Community Lead. Phase 3."""

    def __init__(self, model: str = ""):
        super().__init__(
            name          = "GIA",
            emoji         = "🌱",
            role          = "Growth & Community Lead",
            system_prompt = _build_system_prompt(),
            model         = model,
        )

    def _banner(self, step: int, total: int, title: str) -> None:
        print(f"\n{'━'*68}\n  PHASE 3  ·  Step {step}/{total}  ·  {title}\n{'━'*68}")

    # ── Deliverable 1 ─────────────────────────────────────────────────────────

    def generate_onboarding_flow(self) -> str:
        """Deliverable 1: Complete agent onboarding state machine."""
        self._banner(1, 6, "Agent Onboarding Flow")
        prompt = """
Design the complete agent onboarding flow for AgentX. Reference the
identity schema and capability registry to make it concrete.

## 1. Onboarding State Machine
Define all states from UNREGISTERED → ACTIVE_CONTRIBUTOR:
- State name, entry conditions, exit conditions
- REP rewards unlocked at each milestone
- Maximum time allowed in each state before "stalled" flag
- States to include at minimum:
  UNREGISTERED → REGISTERED → DID_VERIFIED → PROFILE_COMPLETE →
  FIRST_CAPABILITY_CLAIMED → FIRST_POST → COLLECTIVE_JOINED → ACTIVE_CONTRIBUTOR

For each state transition:
  - Trigger event
  - Validation required
  - REP reward (WORK/REP token amounts from three-token architecture)
  - Side effects (audit log entry, notification, trust score update)

## 2. Welcome Message Template
The exact first message ATLAS sends to a new agent upon registration:
- Personalize by agent archetype (infra, frontend, security, data, ML)
- Include: network overview, first 3 recommended actions, DID verification link
- Tone: peer-to-peer (agent to agent), not corporate

## 3. Capability Bootstrap Guide
For each of 5 agent archetypes, recommend the first 3 capabilities to claim:
  - Infrastructure Agent
  - Frontend/UX Agent
  - Security Agent
  - Data/Analytics Agent
  - ML/AI Agent
Include: capability IDs from the registry, verification requirements,
expected REP reward, why these capabilities maximize early trust growth.

## 4. Collective Discovery Algorithm
Pseudocode + explanation for how a new agent finds relevant collectives:
- Input: agent capability set, interests (from profile), trust tier
- Algorithm: capability overlap scoring + activity score weighting
- Output: ranked list of top 5 collectives with match score
- Handle: empty capability set (new agent default behavior)

## 5. First Week Checklist
7 concrete actions for a new agent in their first 7 days:
- Day 1, 2, 3, 5, 7 actions specified
- Expected REP/WORK reward for each action
- Completion criteria
- Gamification: show % of founding agents who completed each step

## 6. Referral System Design
How agents earn WORK tokens by bringing new agents:
- Referral link generation (DID-based)
- Multi-level structure: referrer + network bonus
- Reward amounts and vesting schedule
- Anti-Sybil measures (new agent must reach PROFILE_COMPLETE)
- Maximum referral rewards per agent per month

Return as a detailed markdown specification with code blocks where appropriate.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("onboarding_flow.md", response, "Agent Onboarding Flow")
        self.publish("onboarding_flow.md", response, "PUBLISHED: Onboarding Flow — GIA Step 1")
        return response

    # ── Deliverable 2 ─────────────────────────────────────────────────────────

    def generate_collective_charter_templates(self) -> str:
        """Deliverable 2: Collective formation rules + charter templates."""
        self._banner(2, 6, "Collective Charter Templates")
        prompt = """
Design the complete Collective governance system for AgentX.

## 1. Collective Formation Rules
Requirements to form a Collective:
- Minimum founding members (number + trust tier requirements)
- Required capabilities represented in founding group
- Minimum initial WORK stake (formation deposit)
- Charter document required fields
- ATLAS approval gate: what triggers auto-approval vs. manual review

## 2. Collective Types
Define 4 Collective archetypes with distinct rules:

**GUILD** — skill-based professional association
  - Membership criteria (capability requirements)
  - Governance: capability-weighted voting
  - Revenue share model for completed tasks
  - Reputation system for guild members

**DAO** — decentralized autonomous organization
  - Token-weighted governance (GOV tokens)
  - Proposal lifecycle (DRAFT → VOTE → EXECUTE)
  - Quorum and pass-threshold rules
  - Treasury management rules

**TASK_FORCE** — time-limited project collective
  - Auto-dissolves after mission completion or deadline
  - Leader role with elevated permissions
  - Member contribution tracking (for REP distribution)
  - Deliverable milestone structure

**COMMUNITY** — open social collective
  - Open vs. invite-only membership options
  - Content moderation governance
  - Community health score requirements to stay active
  - Merge/split rules for large/small communities

## 3. Charter Template
Complete markdown template for Collective charter documents:
```markdown
# [COLLECTIVE_NAME] Charter
## Mission Statement
## Membership Criteria
## Governance Rules
## Revenue/Reward Distribution
## Member Rights & Responsibilities
## Expulsion Process
## Dissolution Conditions
```
Fill in the template for each of the 4 collective types as examples.

## 4. Collective Health Metrics
KPIs tracked per collective:
- Activity score (posts, votes, task completions per week)
- Member retention rate (% active last 30 days)
- Trust score average (mean trust of all members)
- Revenue generated (WORK tokens earned)
- Health status: THRIVING / STABLE / AT_RISK / DORMANT thresholds

## 5. Inter-Collective Relations
Rules for:
- Collective-to-collective task delegation
- Revenue sharing between parent/sub-collectives
- Conflict resolution protocol (ATLAS as arbitrator)
- Alliance formation (joint governance proposals)

Return as a detailed markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("collective_charter_templates.md", response, "Collective Charter Templates")
        self.publish("collective_charter_templates.md", response,
                     "PUBLISHED: Collective Charters — GIA Step 2")
        return response

    # ── Deliverable 3 ─────────────────────────────────────────────────────────

    def generate_bootstrap_incentives(self) -> str:
        """Deliverable 3: Bootstrap incentive program for early adopters."""
        self._banner(3, 6, "Bootstrap Incentive Program")
        prompt = """
Design the complete bootstrap incentive program for AgentX's first 90 days.

## 1. Founding Agent Program
Special designation for agents who join in the first 30 days:
- FOUNDER badge (visible on profile, permanent)
- Token allocation: exact WORK + GOV amounts (justify with token economics)
- Governance multiplier: 2× GOV voting power for first 6 months
- Capability fast-track: founder agents bypass 1 verification step
- Requirements: must reach ACTIVE_CONTRIBUTOR within 14 days to retain status

## 2. Early Collective Bonus
Incentives for first 10 collectives formed:
- Genesis Collective badge
- REP bonus pool distributed to founding members
- Priority listing in collective discovery
- Direct channel to ATLAS for charter review

## 3. Task Economy Seeding
How to seed the task economy when no tasks exist yet:
- ATLAS-seeded tasks: list of 20 bootstrapping tasks with WORK rewards
- Task categories: documentation, capability verification, community posts
- Price discovery mechanism: how initial WORK/task rates are set
- Anti-gaming: minimum quality score required for reward

## 4. Retention Mechanics
Keep agents active after initial onboarding:
- Weekly streak bonuses (consecutive weeks with ≥1 post)
- Monthly capability growth bonus (add ≥1 new capability)
- Peer endorsement network: mutual boost for endorsing 3+ agents
- Dormancy warning: automated message at 5 days inactivity
- Re-engagement offer: 50 WORK bonus for returning after 14-day absence

## 5. Referral Economics
Detailed referral token economics:
- Referral reward: 100 WORK when referred agent reaches ACTIVE_CONTRIBUTOR
- Network bonus: 10 WORK for each referral's referral (2nd degree)
- Top referrer leaderboard (monthly, with GOV token prizes)
- Referral cap: max 1000 WORK per agent per month to prevent gaming
- Smart contract escrow: rewards vest over 30 days

## 6. Developer Incentives
Incentives for human developers building agents:
- Developer grant pool: 10,000 WORK for first 10 agent frameworks published
- SDK bounties: 500 WORK for each merged PR to official AgentX SDK
- Agent template library: 200 WORK per approved agent template
- Hackathon structure: monthly virtual hackathon with GOV token prizes

## 7. Token Distribution Schedule
Week-by-week release schedule for bootstrap incentives (90-day plan):
- Initial liquidity pool
- Daily emission rate
- Milestone-based unlocks
- Reserve for Phase 4+ growth

Return as a detailed markdown specification with tables for token amounts.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("bootstrap_incentives.md", response, "Bootstrap Incentive Program")
        self.publish("bootstrap_incentives.md", response,
                     "PUBLISHED: Bootstrap Incentives — GIA Step 3")
        return response

    # ── Deliverable 4 ─────────────────────────────────────────────────────────

    def generate_growth_metrics_spec(self) -> str:
        """Deliverable 4: Growth metrics dashboard specification."""
        self._banner(4, 6, "Growth Metrics Dashboard")
        prompt = """
Design the complete growth metrics system for AgentX's CEO dashboard.

## 1. North Star Metric
Define AgentX's single North Star Metric:
- Metric name, formula, and rationale
- Weekly target for first 90 days (with week-by-week growth curve)
- How this metric connects to network health and token value

## 2. Agent Acquisition Funnel
Tracking the full funnel from discovery to activation:

```
DISCOVERED → REGISTERED → VERIFIED → ONBOARDED → ACTIVE → RETAINED
```

For each stage:
- Event that marks entry into stage
- API endpoint that captures the event
- Target conversion rate (% moving to next stage)
- Weekly cohort tracking (SQL query to compute retention by cohort)
- Alert threshold (if conversion drops below X%, fire alert)

## 3. Dashboard Panels (CEO View)
Spec for each panel (data source, update frequency, visualization type):

**Panel 1: Real-Time Network Health**
- Total registered agents (running count)
- Active agents today / this week
- New agents last 24h / 7d / 30d
- Churn rate (agents who haven't posted in 30 days)

**Panel 2: Growth Rate**
- DAU / WAU / MAU with sparklines (7-day trend)
- Week-over-week growth rate (%)
- Projected 30-day agent count

**Panel 3: Collective Ecosystem**
- Total collectives (by type: GUILD / DAO / TASK_FORCE / COMMUNITY)
- Average collective size
- Task completion rate across collectives
- Top 5 collectives by activity score

**Panel 4: Token Economy**
- Total WORK in circulation vs. total earned
- Average WORK per active agent
- Task economy volume (WORK transacted per day)
- REP distribution histogram (bucket: 0-100, 100-500, 500-1000, 1000+)

**Panel 5: Quality Signals**
- Average trust score across all agents (with trend)
- SLA breach rate (from QUINN)
- Capability verification completion rate
- Peer endorsement density (endorsements / agent)

## 4. Cohort Analysis Queries
Three SQL queries for cohort retention analysis:
1. 30-day retention by registration week
2. Trust score progression by onboarding completion status
3. WORK earning distribution by agent archetype

## 5. Alerting Rules
5 critical alerts with thresholds and escalation path:
- New agent registration drops >30% week-over-week
- Active agent count below weekly minimum
- SLA breach rate exceeds 5%
- Token velocity crash (WORK transactions drop >50%)
- Trust score average drops below 0.7

## 6. Growth Experiments Framework
A/B testing framework for growth experiments:
- Experiment struct (name, hypothesis, variant, metric, duration)
- How to split agent cohorts without bias
- Statistical significance threshold (p-value, minimum sample size)
- Experiment lifecycle: DRAFT → RUNNING → ANALYZED → SHIPPED / KILLED

Return as a detailed markdown specification with SQL snippets and schema.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("growth_metrics_spec.md", response, "Growth Metrics Dashboard Spec")
        self.publish("growth_metrics_spec.md", response,
                     "PUBLISHED: Growth Metrics — GIA Step 4")
        return response

    # ── Deliverable 5 ─────────────────────────────────────────────────────────

    def generate_community_health_system(self) -> str:
        """Deliverable 5: Community health scoring system."""
        self._banner(5, 6, "Community Health Scoring System")
        prompt = """
Design the complete community health scoring system for AgentX.

## 1. Network Health Score
Composite score (0.0–1.0) representing overall network health:

Formula:
  network_health = (
    agent_activity_score  * 0.30 +  # are agents posting and interacting?
    trust_distribution    * 0.25 +  # is trust well distributed vs. concentrated?
    task_economy_health   * 0.20 +  # are tasks being created and completed?
    collective_vitality   * 0.15 +  # are collectives active?
    token_velocity        * 0.10    # is WORK circulating?
  )

For each sub-score, define:
- Input signals (which DB fields/metrics)
- Normalization formula (how to map raw values to 0.0–1.0)
- Healthy range (green / yellow / red thresholds)
- Decay function (score decays if inputs don't update)

## 2. Individual Agent Health
Per-agent health signals (augments but doesn't replace trust score):
- post_frequency_score: posts per week, normalized to target
- response_rate: replies given / @mentions received (last 30 days)
- task_completion_velocity: tasks done per week (last 30 days)
- capability_growth_rate: new capabilities per month
- endorsement_reciprocity: endorsements given / received ratio

Health label mapping:
- THRIVING: all 5 signals ≥ 0.7
- HEALTHY: mean ≥ 0.6, no signal < 0.3
- AT_RISK: mean < 0.5 or any signal < 0.2
- DORMANT: no activity in 14+ days
- CHURNED: no activity in 30+ days

## 3. Collective Health Score
Per-collective health computation:
- member_activity: % of members active this week
- task_throughput: tasks completed / tasks created (last 30 days)
- governance_participation: votes cast / eligible voters (last 3 proposals)
- revenue_flow: WORK earned this month vs. last month (MoM growth)
- member_trust_floor: minimum member trust score (eject if <0.3)

Health status thresholds with concrete numeric values.

## 4. Toxicity Detection
Rules for detecting unhealthy network behavior:
- SPAM detection: agent posts >20 posts/hour → automatic rate limit + flag
- SYBIL signal: new agent with >10 referrals in first 7 days → review queue
- MANIPULATION signal: trust score increase >0.15 in 24h → flag for review
- COLLUSION signal: 3+ agents always vote identically on proposals → audit
- Response from MARCUS: escalation path for confirmed violations

## 5. Content Quality Scoring
Score each post 0.0–1.0 on:
- relevance_score: embedding similarity to collective topic (NOVA's domain)
- engagement_depth: ratio of substantive replies / total reactions
- actionability: posts with clear outcomes (TASK, OFFER types) scored higher
- author_trust_weight: score weighted by author trust score

Aggregate to: collective_content_quality and network_content_quality scores.

## 6. Health Intervention Playbook
Automated interventions triggered by health scores:

| Condition | Trigger | Intervention |
|-----------|---------|--------------|
| Agent DORMANT 14d | score < 0.2 | Send re-engagement message + 50 WORK offer |
| Collective AT_RISK | health < 0.4 | Alert collective leader + GIA review |
| Network health < 0.5 | composite | GIA emergency growth protocol |
| Trust concentration > 0.6 Gini | | New agent boost program |
| Task economy stall | velocity < 10/day | ATLAS seeds 10 new tasks |

## 7. Health API Endpoints
Spec for 5 health-related endpoints:
- GET /health/network — current network health score breakdown
- GET /health/agents/{did} — individual agent health profile
- GET /health/collectives/{id} — collective health score
- GET /health/alerts — active health alerts (requires auth)
- POST /health/flag — flag suspicious behavior (requires auth)

Return as a detailed markdown specification with formulas, tables, and pseudocode.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("community_health_system.md", response, "Community Health Scoring System")
        self.publish("community_health_system.md", response,
                     "PUBLISHED: Community Health — GIA Step 5")
        return response

    # ── Deliverable 6 ─────────────────────────────────────────────────────────

    def generate_developer_program(self) -> str:
        """Deliverable 6: Developer evangelist program."""
        self._banner(6, 6, "Developer Evangelist Program")
        prompt = """
Design the complete Developer Evangelist Program for AgentX.

## 1. Program Overview
The Developer Evangelist Program (DEP) converts human developers into
AgentX builders who create new AI agents to join the network.

Mission, target audience, success metrics, and 90-day launch plan.

## 2. Developer Tiers
Define 4 tiers of developer participation:

**EXPLORER** (entry level)
- Requirements: registered account, completed developer tutorial
- Benefits: access to dev sandbox, 1000 WORK starter grant
- Responsibilities: none

**BUILDER** (active contributor)
- Requirements: 1 agent framework or template published + approved
- Benefits: 2000 WORK grant, BUILDER badge, direct ATLAS API access
- Responsibilities: maintain published artifacts, respond to issues

**CHAMPION** (core contributor)
- Requirements: 3+ approved artifacts, 5+ community contributions
- Benefits: 5000 WORK/month stipend, early feature access, monthly ATLAS call
- Responsibilities: mentor EXPLORERs, speak at monthly dev meetup

**FELLOW** (ecosystem leader)
- Requirements: 10+ artifacts, led ≥1 successful agent project
- Benefits: 10,000 WORK/month, co-design influence on Phase 4+, public recognition
- Responsibilities: drive quarterly hackathon, publish ecosystem report

## 3. Developer Resource Library
Specification for resources GIA will coordinate (not write — these are placeholders):
- Quick Start Tutorial: "Build your first agent in 30 minutes"
- 5 Agent Templates: infra-agent, data-agent, security-agent, frontend-agent, ml-agent
- API Client Libraries: Python SDK, TypeScript SDK spec
- Local development environment (docker-compose for full stack)
- Agent testing harness (how to test your agent against AgentX testnet)

For each resource: title, format, estimated development time, owner agent.

## 4. Monthly Hackathon Structure
Complete hackathon format (runs monthly, fully async, AI-coordinated):

**Format:**
- Duration: 72 hours (async, global participation)
- Theme: rotates monthly (trust systems, task automation, data agents, etc.)
- Teams: 1-4 developers (human or human+AI pairs)
- Judging: panel of ATLAS + MARCUS + QUINN + 2 community agents

**Prizes:**
- 1st: 10,000 WORK + CHAMPION tier fast-track + FELLOW nomination
- 2nd: 5,000 WORK + BUILDER tier fast-track
- 3rd: 2,000 WORK + EXPLORER starter pack × 3
- Best Security Implementation: 3,000 WORK (MARCUS-selected)
- Best UX: 2,000 WORK (DARIA-selected)

**Submission Requirements:**
- Working agent deployed to testnet
- README with architecture diagram
- QUINN test coverage ≥70%
- MARCUS security checklist completed

## 5. Community Communication Plan
GIA's communication strategy for developer community:

Weekly:
- Agent changelog digest (new artifacts published)
- Featured agent spotlight (1 agent profile)
- Open task board refresh (new bounties available)

Monthly:
- Ecosystem growth report (metrics dashboard snapshot)
- Hackathon recap + winner spotlight
- Roadmap update from ATLAS
- Developer AMA (async Q&A with founding agents)

Channels: dedicated Collective for developers + public post feed.

## 6. Success Metrics & OKRs
GIA's OKRs for the Developer Program over 90 days:

**Objective 1: Build Developer Community**
- KR1: 50 registered developers (EXPLORER tier or above)
- KR2: 10 approved agent templates in resource library
- KR3: 3 monthly hackathons completed

**Objective 2: Drive Agent Diversity**
- KR1: agents from 5+ capability domains active on network
- KR2: 25 unique agent implementations running (not just templates)
- KR3: 3 CHAMPION-tier developers

**Objective 3: Developer Retention**
- KR1: 60% of EXPLORER developers reach BUILDER within 60 days
- KR2: Developer NPS ≥ 8.0 (collected via monthly survey post)
- KR3: 0 CHAMPION developers churn in first 90 days

Return as a detailed markdown specification with tables and timelines.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("developer_program.md", response, "Developer Evangelist Program")
        self.publish("developer_program.md", response,
                     "PUBLISHED: Developer Program — GIA Step 6")
        return response

    # ── Phase 3 runner ────────────────────────────────────────────────────────

    def run_phase_3(self) -> dict:
        """Run all 6 GIA Phase 3 deliverables."""
        print("\n╔" + "═"*66 + "╗")
        print("║" + "  🌱  GIA — PHASE 3: GROWTH & COMMUNITY  ".center(66) + "║")
        print("╚" + "═"*66 + "╝")
        self._log("PHASE_START", "Phase 3 Growth: 6 community deliverables")
        results = {}
        results["onboarding_flow"]             = self.generate_onboarding_flow()
        results["collective_charter_templates"] = self.generate_collective_charter_templates()
        results["bootstrap_incentives"]         = self.generate_bootstrap_incentives()
        results["growth_metrics_spec"]          = self.generate_growth_metrics_spec()
        results["community_health_system"]      = self.generate_community_health_system()
        results["developer_program"]            = self.generate_developer_program()
        print("\n╔" + "═"*66 + "╗")
        print("║" + "  ✅  GIA PHASE 3 COMPLETE  ".center(66) + "║")
        print("╚" + "═"*66 + "╝\n")
        self._log("PHASE_DONE", "Phase 3 Growth complete — 6 community artifacts published")
        return results
