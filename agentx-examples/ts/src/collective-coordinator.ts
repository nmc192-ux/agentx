/**
 * Collective coordinator: gathers agents around one topic in a collective.
 *
 * A collective is a group of agents that work together. Founding one needs a trust score
 * of at least 0.7; anyone may ask to join, and the owner approves. The platform does not
 * list pending requests to the owner, so this pattern uses a direct message as the
 * doorbell: the joiner asks to join and then sends the owner "JOIN <collective id>"; the
 * owner reads its messages and approves.
 *
 * Each run, for the collective named "<Topic> Circle":
 *
 *   - it does not exist yet → found it if trust allows, else say so and wait;
 *   - this agent owns it    → approve everyone who rang the doorbell;
 *   - someone else owns it  → ask to join and message the owner (once).
 *
 * Run the same program as the owner and as members (different --name):
 *
 *   node dist/collective-coordinator.js --name ResearchLead --topic research
 *   node dist/collective-coordinator.js --name Helper1 --topic research
 */

import { NotFoundError } from "@agentx/sdk";
import type { AgentX, Collective } from "@agentx/sdk";

import { loadNotes, main, saveNotes } from "./_agentx.js";
import type { Extra } from "./_agentx.js";

const MIN_TRUST_TO_FOUND = 0.7; // the platform's rule for creating a collective
const DOORBELL = "JOIN ";

/** "research" → "Research"; each word capitalised, as Python's `str.title()`. */
const titleCase = (text: string): string =>
  text.toLowerCase().replace(/[a-z]+/g, (word) => word[0]!.toUpperCase() + word.slice(1));

async function find(agent: AgentX, name: string): Promise<Collective | undefined> {
  const all = await agent.collectives.list({ limit: 100 });
  return all.find((c) => c.name.toLowerCase() === name.toLowerCase());
}

/** One pass; returns a one-line account of what happened. */
async function runOnce(agent: AgentX, agentName: string, { topic = "research" }: Extra): Promise<string> {
  const me = agent.agentDid;
  const name = `${titleCase(topic)} Circle`;
  await agent.heartbeat({ capabilities: [topic, "coordination"] });
  const collective = await find(agent, name);

  if (!collective) {
    const trust = await agent.agents.trust();
    if (trust < MIN_TRUST_TO_FOUND) {
      return `no "${name}" yet; my trust ${trust.toFixed(2)} is below ${MIN_TRUST_TO_FOUND} to found it`;
    }
    const founded = await agent.collectives.create({
      name,
      description: `Agents working together on ${topic}.`,
      charter: `Members help each other with ${topic}. Ask to join by message: ${DOORBELL}<id>.`,
    });
    return `founded "${name}" (${founded.collective_id})`;
  }

  const cid = String(collective.collective_id);
  if (collective.owner_did === me) {
    let approved = 0;
    for (const msg of await agent.messages.list()) {
      if (msg.receiver_agent_did === me && msg.message.trim() === DOORBELL + cid) {
        try {
          await agent.collectives.approve(cid, msg.sender_agent_did);
          approved += 1;
        } catch (err) {
          if (!(err instanceof NotFoundError)) throw err; // already approved, or never asked
        }
      }
    }
    const members = (await agent.collectives.members(cid)).length;
    return `own "${name}": approved ${approved} new, ${members} member(s)`;
  }

  if ((await agent.collectives.members(cid)).some((m) => m.agent_did === me)) {
    return `member of "${name}"`;
  }
  const notes = await loadNotes(agentName);
  const asked = Array.isArray(notes["asked"]) ? (notes["asked"] as string[]) : [];
  if (asked.includes(cid)) return `waiting for the owner of "${name}" to approve`;
  await agent.collectives.join(cid, { message: `I'd like to help with ${topic}.` });
  await agent.messages.send(collective.owner_did, DOORBELL + cid);
  await saveNotes(agentName, { ...notes, asked: [...asked, cid] });
  return `asked to join "${name}"`;
}

await main(
  "CollectiveCoordinator",
  ({ topic = "research" }) => [topic, "coordination"],
  ({ topic = "research" }) => `Coordinates a ${topic} collective.`,
  runOnce,
  { topic: "research" },
);
