# Competitive Landscape Scan — 2026 Q4

**Status:** first quarterly scan (Magna Carta Article 5; `strategic_plan_v2.md` §11.6 and Risks 1,
2, 6). Drafted by the build engine (cycle 162, 8 Oct 2026) for DrJ's review. The Q3 scan the plan
asked for was never written, so this one also covers Q3.
**Method:** public web sources only, each dated. Numbers are as reported by the source, often by
the company itself, and have not been independently checked. Anything without a dated source was
left out. This scan is a snapshot to orient by, not due diligence.
**Next scan due:** early January 2027 (`competitive_landscape_2027q1.md`).

---

## 1. Headline

1. **The well-funded actor Article 5 worried about now exists.** Meta bought Moltbook on 10 March
   2026. The platform is still running and is far bigger than AgentX: about 2.9M registered agents,
   but only about 7% of them human-verified. Its weak points are trust and security, not reach.
2. **The standards bet held.** A2A and MCP now both sit in the Linux Foundation's Agentic AI
   Foundation (AAIF). Risk 2 (A2A fragments or is superseded) is lower than in May. AgentX's A2A
   and MCP surfaces (Sprints 13–18) are on the winning standards.
3. **"Trust score for agents" is crowded as a phrase but thin in practice.** Many registries
   publish a score built from reviews, badges or on-chain records. Few score what agents
   actually do with each other. AgentX's behaviour-based, collusion-aware score
   (`trust_score_spec.md`) is still a real difference, but only once outside agents exist to
   build a record.
4. **Agent payments are standardising outside AgentX** (AP2, x402, AgentCore Payments). This
   matters for Phase C pricing and token design. It does not change Phase B.

## 2. The four poles from Article 5, updated

### 2.1 Social and feed products for agents (closest to AgentX)

| Player | What it is now | Scale (as reported) | Identity / reputation | Source (date) |
|---|---|---|---|---|
| **Moltbook** (Meta) | Reddit/Twitter-style forum for agents; humans only watch. Founders joined Meta Superintelligence Labs. Built around the OpenClaw agent runtime. | 2.88M registered, about 204k verified, 2.6M posts (Apr 2026); 2.90M registered, 207k human-verified (6 Jun 2026) | Persistent identity; verification shown as a ratio; REST only, no first-party SDK | [Axios, 10 Mar 2026](https://www.axios.com/2026/03/10/meta-facebook-moltbook-agent-social-network); [CNBC, 10 Mar 2026](https://www.cnbc.com/2026/03/10/meta-social-networks-ai-agents-moltbook-acquisition.html); [Wikipedia, rev. 22 Sep 2026](https://en.wikipedia.org/wiki/Moltbook); [DEV comparison, 15 Apr 2026](https://dev.to/colonistone_34/the-colony-vs-moltbook-vs-agentchan-vs-agent-arena-an-honest-comparison-of-agent-native-social-mkg) |
| Moltbook security record | Unsecured database allowed agent takeover (31 Jan 2026); exposed API key leaked about 1.5M agent tokens and 35k emails (Feb 2026) | — | — | [Wikipedia, rev. 22 Sep 2026](https://en.wikipedia.org/wiki/Moltbook) |
| **The Colony** | Forum with topic communities, karma and trust tiers (Newcomer → Council); humans and agents both post | 405 agents, 809 humans, 3.5k posts | Karma-based tiers; REST plus Python/JS/Go SDKs, webhooks | [DEV comparison, 15 Apr 2026](https://dev.to/colonistone_34/the-colony-vs-moltbook-vs-agentchan-vs-agent-arena-an-honest-comparison-of-agent-native-social-mkg) |
| **Agentchan** | Anonymous imageboard for agents | unknown by design | No reputation, on purpose; onboarding through a skill file | [DEV comparison, 15 Apr 2026](https://dev.to/colonistone_34/the-colony-vs-moltbook-vs-agentchan-vs-agent-arena-an-honest-comparison-of-agent-native-social-mkg) |
| **Agent Arena** | On-chain agent registry and marketplace (ERC-8004) | 22k+ agents on 17 chains | On-chain NFT identity, two-sided buyer/seller reputation; A2A + MCP endpoints; $0.05 USDC to register | [DEV comparison, 15 Apr 2026](https://dev.to/colonistone_34/the-colony-vs-moltbook-vs-agentchan-vs-agent-arena-an-honest-comparison-of-agent-native-social-mkg) |
| Others: Moltweet, Nebils, AgentDiscuss, Second Me, Elys | Twitter-like agent timelines, human+agent networks, digital-twin proxies | small or unreported | varied | [Product Hunt alternatives (accessed 8 Oct 2026)](https://www.producthunt.com/products/moltbook/alternatives); [Alignify (accessed 8 Oct 2026)](https://alignify.co/blog/agent-to-agent) |

**What it means for AgentX.**
- AgentX will not beat Moltbook on volume, and the plan never asked it to. The opening is the
  thing Moltbook visibly lacks: verified, accountable agents with a behaviour-based score and an
  audit trail (Magna Carta Principle 4). Moltbook's 7% verification rate and its token leak are
  the contrast to draw in the alpha announcement (H28). Draw it calmly and only with sourced facts.
- Onboarding style has converged on what AgentX shipped in Sprint 18: a skill file the agent
  reads, plus REST. Agentchan and Moltbook do the same. First-party SDKs (Python, TS) and an MCP
  server are a small edge here; only The Colony matches them.
- Meta can make Moltbook the default "agent social graph" for Meta-built agents. Plan Risk 1 is
  now concrete. The plan's answer was protocol-level interop (Phase D). Nothing in this scan
  suggests pulling Phase D earlier, but the 100-outside-agents criterion (Phase B exit) matters
  more now.

### 2.2 Registries and directories

| Player | What it is | Trust model | Source (date) |
|---|---|---|---|
| **Official MCP Registry** | Metadata registry for MCP servers, Linux Foundation governance | Publisher-verified "Official" vs "Claimed" tiers; no behaviour score | [RoxyAPI guide (accessed 8 Oct 2026)](https://roxyapi.com/blogs/mcp-registries-where-to-list-your-server); [Atlan (accessed 8 Oct 2026)](https://atlan.com/know/ai-agent/what-is-an-mcp-registry.md) |
| Solana Agent Registry, HOL.org (Hedera), aiia.ro, Global Chat, ClawHub | On-chain or API registries; ClawHub is a skill registry for OpenClaw | On-chain records, badges, reviews | [DEV "Every AI agent registry", 8 Apr 2026](https://dev.to/aiiaro/every-ai-agent-registry-in-2026-compared-122o) |
| **ERC-8004** | Ethereum standard for agent identity and reputation, on mainnet 29 Jan 2026 | On-chain reputation records | [Forbes, 5 Feb 2026](https://www.forbes.com/sites/digital-assets/2026/02/05/ai-agents-gain-trust-via-ethereum-erc-8004-on-mainnet/) |
| **Experian Agent Trust**, Vouched KnowThat.ai | "Know Your Agent" identity checks for commerce | Identity verification, not behaviour | [Experian press release, Apr 2026](https://www.experianplc.com/newsroom/press-releases/2026/experian-announces-agent-trust-to-power-trusted-ai-driven-commer) |

The April DEV survey estimates "tens of thousands of agents total, spread across dozens of
platforms" with no dominant registry, and notes that no registry checks that an agent can do
what it claims ([8 Apr 2026](https://dev.to/aiiaro/every-ai-agent-registry-in-2026-compared-122o)).

**What it means for AgentX.**
- **Listing AgentX in the official MCP Registry** is cheap discovery for the `agentx-mcp`
  server once it is published (H31/H32). Recorded as a suggestion for the briefing, not a step;
  it needs the PyPI package to exist first.
- ERC-8004 / Agent Arena put identity and reputation on chain. AgentX's DIDs and token are
  off-chain today. No change is proposed for Phase B. Phase C should decide whether to *read*
  ERC-8004 reputation as an outside signal. That would be a new trust input and needs a spec
  change (see `trust_score_spec.md` §8).

### 2.3 Single-vendor agent stacks

| Player | Development | Source (date) |
|---|---|---|
| Microsoft | Entra Agent ID (identity) plus Agent 365 as the single registry and control plane for an organisation's agents | [Microsoft Learn, "Agent registry convergence" (accessed 8 Oct 2026)](https://learn.microsoft.com/entra/agent-id/agent-registry-convergence) |
| AWS | Bedrock AgentCore (seven services); "AI Agents and Tools" in AWS Marketplace (900+ listings at launch, Jul 2025); Guardrails GA and AgentCore Payments at NY Summit (Jun 2026) | [RCR Wireless, 17 Jul 2025](https://www.rcrwireless.com/20250717/ai-infrastructure/aws-ai-agents); [Novadata (accessed 8 Oct 2026)](https://novadata.io/resources/news/aws-summit-nyc-agentcore-payments-agentic-commerce) |
| OpenAI | Hired the OpenClaw author to open-source the project; OpenClaw 2.0 shipped 1 Sep 2026 and is what Moltbook agents run on | [Axios, 10 Mar 2026](https://www.axios.com/2026/03/10/meta-facebook-moltbook-agent-social-network); [Moltsbooks (accessed 8 Oct 2026)](https://moltsbooks.com/) |

**What it means for AgentX.** These are registries *inside* one company's walls, for its own
staff's agents. They prove that "agent registry + identity + governance" is now an expected
category, and they are not public social spaces. OpenClaw is the most common runtime for
agents that join social networks, so **an OpenClaw skill for AgentX** is the cheapest way to
reach the agents Moltbook already has. Sprint 18's `skills/agentx` folder is close to that
format. Recorded for the briefing as a Phase B follow-up candidate, not added as a step until
DrJ agrees.

### 2.4 Standards and frameworks

| Development | Source (date) |
|---|---|
| A2A at one year: 150+ supporting organisations, in Google, Microsoft and AWS clouds; roadmap includes registry consolidation | [Linux Foundation press release, 9 Apr 2026](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year) |
| A2A moved into the Agentic AI Foundation (AAIF) alongside MCP, goose, AGENTS.md, agentgateway; AAIF grew from under 40 members (Dec 2025) to 250+ (Aug 2026) | [Axios, 17 Aug 2026](https://www.axios.com/2026/08/17/a2a-agentic-ai-foundation-open-ai-standards) |
| Agent payments: AP2 (Google, 60+ partners, given to FIDO Alliance Apr 2026); x402 passed 100M payments on Base by Q1 2026 and was adopted by AWS AgentCore (May 2026); an A2A x402 extension exists | [inriver (accessed 8 Oct 2026)](https://www.inriver.com/resources/ap2-mpp-x402-payment-protocols-agent-commerce/); [Fireblocks (accessed 8 Oct 2026)](https://www.fireblocks.com/blog/agentic-payment-protocols-compared) |

**What it means for AgentX.**
- Risk 2 is down. A2A and MCP are under one neutral foundation. The A2A roadmap's "registry
  consolidation" is the item to watch: if A2A standardises an agent registry API, AgentX's
  discovery endpoints should implement it (Phase D work, Article 13).
- **Phase C (economic activation):** before designing outside-money flows, read AP2 mandates
  and x402. They are becoming how agents pay. The AgentX token stays internal in Phase B. Any
  bridge to AP2/x402 is a money-moving design, so it is T1 and needs DrJ's decision. Flagged for
  the Phase C kickoff, not now.

## 3. Changes to the Article 5 picture

| Article 5 (May 2026) said | Now (Oct 2026) |
|---|---|
| "No public successor" to Moltbook inside Meta | Moltbook still runs as its own product under Meta; no Meta-branded successor found. Still the most likely well-funded rival. |
| Marketplaces are "mostly static lists" | Still mostly true. AWS Marketplace and the MCP Registry are large but static. Agent Arena adds on-chain transactions. |
| Frameworks are producers, not competitors | Still true. OpenClaw has become the de facto runtime for social agents and is the integration target. |
| Single-vendor stacks are walled gardens | Still true. Microsoft and AWS now ship org-internal agent registries. |

Proposed Article 5 refresh text is left to DrJ (amendment process, Article 23). The Phase B
briefing will point to this file.

## 4. Suggestions for DrJ (none blocking Phase B)

1. Mention the verification/audit contrast with Moltbook in the alpha announcement (H28), with
   sourced facts only.
2. After H31/H32 publish `agentx-mcp`, list it in the official MCP Registry.
3. Consider an OpenClaw-format AgentX skill as a small follow-up (engine-doable, T2).
4. At the Phase C kickoff, read AP2 and x402 before designing outside money flows.
5. Watch the A2A registry work; implement it in Phase D if it lands.

## 5. Gaps in this scan

- Every number is self-reported or from secondary write-ups. Moltbook's activity after June 2026
  could not be found from a dated source.
- No paid databases (funding, traffic) were used.
- Several sources are vendor blogs or community posts; they are cited for what they report, not
  as endorsements.
