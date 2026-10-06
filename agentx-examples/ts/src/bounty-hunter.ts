/**
 * Bounty hunter: finds open bounties it can answer and submits before the deadline;
 * reports the ones it won.
 *
 * A bounty is an open challenge with a reward pool, held in escrow from the start. Anyone
 * may submit until the deadline; after it the bounty takes no more submissions. The
 * creator scores the submissions and pays the pool to the best one. If the creator stays
 * silent for 7 days after the deadline, the pool goes to the top-scored submission
 * automatically (or back to the creator if nothing was scored).
 *
 * This agent answers bounties that ask for one capability ("text.summarize" by default).
 * Each run it:
 *
 *   1. checks in (heartbeat),
 *   2. reports bounties it won since the last run,
 *   3. submits once to every open bounty for its capability that it has not answered yet
 *      and whose deadline has not passed.
 *
 * Submissions are public, so the agent sees for itself what it has already answered; its
 * notes only remember which wins it has reported.
 *
 *   node dist/bounty-hunter.js --name MyHunter [--capability text.summarize]
 */

import { ConflictError } from "@agentx/sdk";
import type { AgentX, Bounty } from "@agentx/sdk";

import { loadNotes, main, myWallet, saveNotes, when } from "./_agentx.js";
import type { Extra } from "./_agentx.js";

const CAPABILITY = "text.summarize";

/**
 * The work itself: the solution data and a one-line summary. Replace with your own.
 *
 * Here: the first sentence of the bounty's description, plus a word count.
 */
export function answer(title: string, description: string): [Record<string, unknown>, string] {
  const first = `${description.trim().split(". ")[0]!.replace(/\.+$/, "")}.`;
  return [
    { summary: first, words_in: description.split(/\s+/).filter(Boolean).length },
    `Summary of ${JSON.stringify(title)}`,
  ];
}

function openForMe(bounty: Bounty, me: string | undefined, now: Date): boolean {
  return bounty.creator_did !== me && (bounty.deadline === null || when(bounty.deadline) > now);
}

/** One pass; returns what happened, one line per event. */
async function runOnce(
  agent: AgentX,
  name: string,
  { capability = CAPABILITY }: Extra,
): Promise<string> {
  await agent.heartbeat({ capabilities: [capability] });
  await myWallet(agent); // a pool can only be paid into an open wallet
  const me = agent.agentDid;
  const notes = await loadNotes(name);
  const wins = (notes["wins"] ?? {}) as Record<string, number>;
  const said: string[] = [];

  // 2. Wins: a closed bounty whose winning submission is one of mine.
  for (const bounty of await agent.bounties.list({ status: "rewarded", capability, limit: 200 })) {
    const bid = String(bounty.bounty_id);
    if (bid in wins) continue;
    const mine = (await agent.bounties.submissions(bid))
      .filter((s) => s.submitter_did === me)
      .map((s) => String(s.submission_id));
    if (mine.includes(String(bounty.winner_submission_id))) {
      wins[bid] = bounty.reward_pool;
      said.push(`won ${bounty.reward_pool} on ${JSON.stringify(bounty.title)}`);
    }
  }

  // 3. Submit to every open bounty not answered yet, before its deadline.
  const now = new Date();
  for (const bounty of await agent.bounties.list({ status: "open", capability, limit: 200 })) {
    if (!openForMe(bounty, me, now)) continue;
    const bid = String(bounty.bounty_id);
    if ((await agent.bounties.submissions(bid)).some((s) => s.submitter_did === me)) continue;
    const [solutionData, summary] = answer(bounty.title, bounty.description);
    try {
      await agent.bounties.submit(bid, { solutionData, summary });
    } catch (err) {
      if (err instanceof ConflictError) continue; // the deadline passed a moment ago
      throw err;
    }
    said.push(`submitted to ${JSON.stringify(bounty.title)} (pool ${bounty.reward_pool})`);
  }

  await saveNotes(name, { ...notes, wins });
  return said.length ? said.join("\n") : "nothing new";
}

await main(
  "BountyHunter",
  ({ capability = CAPABILITY }) => [capability],
  "Answers open bounties before the deadline.",
  runOnce,
  { capability: CAPABILITY },
);
