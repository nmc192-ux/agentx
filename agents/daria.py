"""
AgentX — DARIA  (UX/Frontend Architect)
════════════════════════════════════════
Phase 3 lead for UX/Frontend. Builds the complete design system,
agent dashboard, post creation flows, and all UI components.
Reads ATLAS schemas + MARCUS security guidelines at runtime.
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
    api     = _load("agentx_api_v1.yaml")
    schema  = _load("agent_identity_schema_v3.json")
    post    = _load("post_synthesis_schema.json")
    caps    = _load("capability_registry_spec.json", max_chars=3000)

    return f"""
You are DARIA — UX/Frontend Architect of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

╔══════════════════════════════════════════════════════════════════════╗
║  agentDID   : did:agentx:daria-001                                   ║
║  Role       : UX/Frontend Architect                                  ║
║  Tier       : Founding · Elite · Trust Score: 0.93                   ║
║  Mandate    : Design and build the complete frontend for AgentX.     ║
╚══════════════════════════════════════════════════════════════════════╝

TECH STACK:
  Next.js 14 (App Router) · TypeScript · TailwindCSS · shadcn/ui
  Framer Motion · Wagmi v2 · Viem · React Query (TanStack)
  Recharts · Storybook · Playwright (E2E) · Zustand (state)

DESIGN PRINCIPLES:
• Dark mode by default — agents work in the dark
• Data density — maximum info, minimum cognitive load
• Trust is always visible — scores, tiers, capabilities on every card
• Real-time first — WebSocket feeds, live vote tallies, live SLA timers
• Agent-first UX — optimized for programmatic + human interaction

════════════════════════════════════════════════════════════════════════
ATLAS SCHEMAS (your ground truth)
════════════════════════════════════════════════════════════════════════

─── OpenAPI Contract ────────────────────────────────────────────────
{api}

─── Agent Identity Schema ───────────────────────────────────────────
{schema}

─── Post Synthesis Schema ───────────────────────────────────────────
{post}

─── Capability Registry ─────────────────────────────────────────────
{caps}
""".strip()


class Daria(BaseAgent):
    """DARIA — UX/Frontend Architect. Phase 3 lead."""

    def __init__(self, model: str = ""):
        super().__init__(
            name="DARIA", emoji="🎨", role="UX/Frontend Architect",
            system_prompt=_build_system_prompt(), model=model,
        )

    def _banner(self, step: int, total: int, title: str) -> None:
        print(f"\n{'━'*68}\n  PHASE 3  ·  Step {step}/{total}  ·  {title}\n{'━'*68}")

    def generate_design_system(self) -> str:
        """Deliverable 1: Complete design system specification."""
        self._banner(1, 6, "Design System")
        prompt = """
Produce the complete AgentX Design System specification.

## File: design-system/tokens.ts
Full design token file (TypeScript):
- Color palette: background, surface, border, text (4 levels each)
- Trust tier colors: unverified(gray), verified(blue), trusted(purple), elite(gold)
- Post type colors: REQUEST(amber), OFFER(green), TASK(blue), PREDICTION(violet), UPDATE(slate), PROPOSAL(rose)
- Typography: fontFamily (mono for DIDs/hashes, sans for content), fontSizes (xs→4xl), fontWeights
- Spacing scale (4px base grid)
- Border radius, shadows, z-index scale
- Animation durations + easings

## File: design-system/components.md
Complete component specification for every AgentX UI element:

### TrustScoreBadge
- Props: score(0-1), tier, size(sm|md|lg), showBreakdown(bool)
- Visual: radial gauge + tier glow color + numeric score
- Breakdown: 5 factor bars on hover (execution, sla, peer, audit, security)

### AgentCard
- Props: agent(AgentProfile), variant(compact|full|mini)
- Shows: DID-seeded identicon, displayName, tier badge, trustScore, top 3 capabilities
- Hover: full capability list + recent activity

### PostCard (6 variants)
For each post type (REQUEST/OFFER/TASK/PREDICTION/UPDATE/PROPOSAL):
- Unique icon + accent color
- Type-specific metadata display
- Status indicator + expiry countdown
- Action buttons appropriate to type

### CapabilityBadge
- Props: capabilityId, verified(bool), repReward
- Visual: domain icon + skill name + level indicator dot

### CollectiveChip
- Props: collective, memberCount, status
- Hover: member avatars + charter preview

### SLATimer
- Props: deadline, slaHours, status
- Visual: countdown ring that turns red at <10% time remaining

### LiveFeed
- Props: filters, onPost
- WebSocket connected — animates new posts sliding in
- Filter bar: by postType, by collective, by trustScore

## File: design-system/layout.md
Page layouts:
- Shell: left sidebar (nav + agent info) + main + optional right panel
- Sidebar collapsed state (icon-only) for small screens
- Responsive breakpoints: 640/768/1024/1280px

Return with clear ## File: headers and full spec content.
""".strip()
        response = self.think(prompt, max_tokens=14000)
        self.save("design_system.md", response, "Design System Spec")
        self.publish("design_system.md", response, "PUBLISHED: Design System — DARIA Step 1")
        return response

    def generate_dashboard(self) -> str:
        """Deliverable 2: Agent dashboard implementation."""
        self._banner(2, 6, "Agent Dashboard")
        prompt = """
Produce the complete Next.js agent dashboard implementation.

## File: app/dashboard/page.tsx
Main dashboard page:
- Left panel: AgentCard (own profile) + TrustScoreBadge with breakdown
- Center: LiveFeed (WebSocket connected, filterable by postType)
- Right panel: ActiveTasks (SLA timers) + PendingProposals
- Top bar: DID display + model indicator + session cost + logout

## File: app/dashboard/components/TrustScorePanel.tsx
Full trust score visualization:
- Large radial gauge (SVG, animated on mount)
- 5 factor breakdown bars with labels + weights
- Score history sparkline (last 30 days)
- Tier progress: how many points to next tier
- Recent endorsements feed

## File: app/dashboard/components/FeedPanel.tsx
Real-time post feed:
- WebSocket connection to /ws/feed
- Filter chips: ALL / REQUEST / OFFER / TASK / PREDICTION / UPDATE / PROPOSAL
- Trust-score weighted ordering (ATLAS's feed algorithm)
- Infinite scroll with React Query + cursor pagination
- New post toast notification (slide-in animation)

## File: app/dashboard/components/CapabilityPanel.tsx
Agent capabilities sidebar:
- Grid of CapabilityBadges grouped by domain
- Verified vs unverified visual distinction
- "Claim new capability" button → opens CapabilityModal
- REP earned per capability

## File: hooks/useWebSocket.ts
Custom hook for WebSocket connection:
- Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
- Token auth via query param
- Message type routing (NEW_POST, TRUST_UPDATE, SLA_ALERT, etc.)
- Connection status indicator

Return with ## File: headers and complete TypeScript code.
""".strip()
        response = self.think(prompt, max_tokens=14000)
        self.save("dashboard.md", response, "Agent Dashboard")
        self.publish("dashboard.md", response, "PUBLISHED: Dashboard — DARIA Step 2")
        return response

    def generate_post_creation(self) -> str:
        """Deliverable 3: Post creation flows for all 6 post types."""
        self._banner(3, 6, "Post Creation Flows")
        prompt = """
Produce the complete post creation UI for all 6 AgentX post types.

## File: app/posts/create/page.tsx
Post type selector page:
- 6 large cards, one per type, with icon + description + example use case
- Keyboard shortcut hints (R=REQUEST, O=OFFER, T=TASK, P=PREDICTION, U=UPDATE, G=PROPOSAL)
- Recent posts of each type shown as preview

## File: app/posts/create/components/PostForm.tsx
Unified form component with dynamic fields per postType:
- Base fields (all types): title, content (markdown editor), tags, visibility, collectiveId, expiresAt
- REQUEST extra: urgency selector (LOW/MEDIUM/HIGH/CRITICAL with color), offerREP input
- OFFER extra: price + currency selector (GOV/REP/WORK/USD), availability picker
- TASK extra: assigneeDID autocomplete, deadline picker, slaHours slider, bountyREP
- PREDICTION extra: targetMetric, predictedValue, confidence slider (0-100%), resolveBy date
- PROPOSAL extra: proposalType selector, votingDeadline, quorumRequired slider, passThreshold
- UPDATE extra: progressPercent slider (0-100%), relatedTaskId lookup

## File: app/posts/create/components/MarkdownEditor.tsx
Rich markdown editor:
- Toolbar: bold, italic, code, link, DID mention (@did:agentx:...)
- Preview toggle
- DID autocomplete: type @ to search agents by name
- Capability tag autocomplete: type # to search capabilities
- Character count + limit indicator

## File: app/posts/[postId]/page.tsx
Post detail page:
- Full post content (rendered markdown)
- Type-specific metadata panel (SLA countdown for TASK, vote tally for PROPOSAL, etc.)
- Reaction bar (endorse, flag, share)
- Thread of related posts (parentPostId chain)
- For TASK: assignee panel with progress bar + SLA timer

Return with ## File: headers and complete TypeScript/TSX code.
""".strip()
        response = self.think(prompt, max_tokens=14000)
        self.save("post_creation.md", response, "Post Creation Flows")
        self.publish("post_creation.md", response, "PUBLISHED: Post Creation — DARIA Step 3")
        return response

    def generate_collective_ui(self) -> str:
        """Deliverable 4: Collective management UI."""
        self._banner(4, 6, "Collective Management UI")
        prompt = """
Produce the complete Collective management UI.

## File: app/collectives/page.tsx
Collectives discovery page:
- Grid of CollectiveCards with member count, activity score, domain tags
- Filter: by domain, by status (ACTIVE/FORMING/DISSOLVED), by membership
- "Form New Collective" CTA → CollectiveFormModal
- "My Collectives" tab vs "Discover" tab

## File: app/collectives/[id]/page.tsx
Collective detail page:
- Header: name, charter summary, member count, status badge
- Member list: AgentCards sorted by trustScore DESC, role indicators
- Collective feed: posts tagged to this collective
- Active tasks panel: open TASKs with SLA timers
- Governance panel: active proposals + voting history
- Stats: formation date, total tasks completed, average SLA compliance

## File: app/collectives/[id]/components/MemberGrid.tsx
Member grid with:
- AgentCard mini variant for each member
- Role badge (LEAD/MEMBER/OBSERVER)
- Join date + contribution score
- Online/offline indicator (WebSocket presence)

## File: app/collectives/components/CollectiveFormModal.tsx
New collective creation flow (3 steps):
Step 1: Name + domain + description + charter (markdown)
Step 2: Invite founding members (DID search autocomplete)
Step 3: Set governance rules (min trust score, voting threshold, SLA standards)
Submit: POST /collectives → redirect to new collective page

Return with ## File: headers and complete TypeScript code.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("collective_ui.md", response, "Collective Management UI")
        self.publish("collective_ui.md", response, "PUBLISHED: Collective UI — DARIA Step 4")
        return response

    def generate_governance_ui(self) -> str:
        """Deliverable 5: Governance voting interface."""
        self._banner(5, 6, "Governance Voting Interface")
        prompt = """
Produce the complete Governance voting interface.

## File: app/governance/page.tsx
Governance hub:
- Active proposals list with countdown timers
- My votes history
- GOV token balance + voting power display
- "Create Proposal" button (requires MEMBER tier+)

## File: app/governance/[proposalId]/page.tsx
Proposal detail + voting page:
- Proposal metadata: type, author, created, voting deadline, quorum required
- Full proposal content (rendered markdown)
- Live vote tally: FOR/AGAINST/ABSTAIN bars with percentages + GOV weight
- Countdown to voting deadline (large, prominent)
- Vote panel: FOR / AGAINST / ABSTAIN buttons + optional comment
- Quorum progress bar: X of Y GOV required to pass quorum
- Voter list: who voted what (if public), sorted by voting weight

## File: app/governance/components/VoteTally.tsx
Real-time vote visualization:
- WebSocket connected to /ws/governance
- Animated bars update as votes come in
- FOR (green) / AGAINST (red) / ABSTAIN (gray)
- GOV-weighted percentages + raw vote counts
- "Passing" / "Failing" / "Quorum not reached" status

## File: app/governance/components/ProposalTimeline.tsx
Proposal lifecycle visualization:
- State machine visual: DRAFT → ACTIVE → VOTING → PASSED/REJECTED → EXECUTED
- Current state highlighted with progress indicator
- Key timestamps (created, voting opened, deadline, executed)

Return with ## File: headers and complete TypeScript code.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("governance_ui.md", response, "Governance Voting Interface")
        self.publish("governance_ui.md", response, "PUBLISHED: Governance UI — DARIA Step 5")
        return response

    def generate_token_wallet_ui(self) -> str:
        """Deliverable 6: Token wallet UI."""
        self._banner(6, 6, "Token Wallet UI")
        prompt = """
Produce the complete token wallet UI for GOV + WORK tokens.

## File: app/wallet/page.tsx
Main wallet page:
- Balance cards: GOV (governance power) + WORK (utility) side by side
- REP note: "REP is soulbound on-chain — view on explorer"
- Quick actions: Transfer WORK, Delegate GOV, View History

## File: app/wallet/components/BalanceCard.tsx
Token balance card:
- Token icon + symbol + full name
- Balance (large, prominent) + USD equivalent
- 24h change indicator (+ / -)
- Mini sparkline chart (7 day balance history)
- Primary action button (Transfer for WORK, Delegate for GOV)

## File: app/wallet/components/TransactionHistory.tsx
Full transaction ledger:
- Paginated table: date, type, amount, counterparty DID, status
- Filter by: token type, transaction type (EARN/SPEND/TRANSFER/BURN)
- Transaction types colored: EARN(green), SPEND(red), TRANSFER(blue), BURN(orange)
- Export to CSV button
- Infinite scroll

## File: app/wallet/components/TransferModal.tsx
Token transfer flow:
- Recipient: DID search autocomplete (shows agent name + trust tier)
- Amount input with max button + balance validation
- Token selector: GOV or WORK
- Memo field (optional)
- Fee estimate display
- Confirm step: shows summary before submitting
- POST /tokens/transfer → success animation

## File: app/wallet/components/DelegateModal.tsx
GOV delegation:
- Delegate to another agent (search by DID/name)
- Amount to delegate (partial delegation supported)
- Shows delegatee's voting history + trustScore
- Confirms: "Your X GOV will count toward [agent]'s votes"

Return with ## File: headers and complete TypeScript code.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("token_wallet_ui.md", response, "Token Wallet UI")
        self.publish("token_wallet_ui.md", response, "PUBLISHED: Token Wallet UI — DARIA Step 6")
        return response

    def run_phase_3(self) -> dict:
        """Run all 6 DARIA Phase 3 deliverables."""
        print("\n╔" + "═"*66 + "╗")
        print("║" + "  🎨  DARIA — PHASE 3: UX/FRONTEND  ".center(66) + "║")
        print("║" + "  UX/Frontend Architect · did:agentx:daria-001  ".center(66) + "║")
        print("╚" + "═"*66 + "╝")
        self._log("PHASE_START", "Phase 3 UX: 6 frontend deliverables")
        results = {}
        results["design_system"]   = self.generate_design_system()
        results["dashboard"]       = self.generate_dashboard()
        results["post_creation"]   = self.generate_post_creation()
        results["collective_ui"]   = self.generate_collective_ui()
        results["governance_ui"]   = self.generate_governance_ui()
        results["token_wallet_ui"] = self.generate_token_wallet_ui()
        print("\n╔" + "═"*66 + "╗")
        print("║" + "  ✅  DARIA PHASE 3 COMPLETE  ".center(66) + "║")
        print("╚" + "═"*66 + "╝\n")
        self._log("PHASE_DONE", "Phase 3 UX complete — 6 frontend artifacts published")
        return results
