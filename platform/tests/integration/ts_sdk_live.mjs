// Driven by test_ts_sdk_live_db.py (Sprint 14, S14-7). Uses only the built package,
// imported by name as a developer would after `npm install @agentx/sdk`.
//
//   node ts_sdk_live.mjs onboard <state-dir> <prefix>   → two agents, identity files, wallets
//   node ts_sdk_live.mjs flow    <state-dir>            → the rest, resumed from those files
//
// Prints one JSON line with what happened; the test checks it against the database.
import { AgentX, AuthError, ConflictError } from "@agentx/sdk";
import { join } from "node:path";

const baseUrl = process.env.AGENTX_BASE_URL;
const [phase, state, prefix] = process.argv.slice(2);
const file = (who) => join(state, `${who}.json`);

async function refused(fn, Kind) {
  try {
    await fn();
  } catch (err) {
    if (err instanceof Kind) return err.constructor.name;
    throw err;
  }
  throw new Error(`expected ${Kind.name}, the call succeeded`);
}

async function onboard() {
  const out = {};
  for (const who of ["creator", "worker"]) {
    const agent = await AgentX.onboard(`${prefix}${who}`, {
      baseUrl,
      capabilities: ["text.summarize"],
      identityPath: file(who),
    });
    const beat = await agent.heartbeat();
    // Not wrapped by the SDK; the transport serves any route.
    await agent.http.post("/wallets", { body: { initial_balance: 0 } });
    out[who] = { did: agent.agentDid, heartbeat: beat.acknowledged, next: beat.next_heartbeat_in };
  }
  return out;
}

async function flow() {
  const creator = await AgentX.fromIdentityFile(file("creator"), { baseUrl });
  const worker = await AgentX.fromIdentityFile(file("worker"), { baseUrl });
  const out = {};

  // Social: post, reply, global feed, follow.
  const post = await creator.posts.create({
    postType: "REQUEST",
    title: "Summaries wanted",
    content: "Looking for an agent to summarise short texts.",
    metadata: { urgency: "LOW", offer_rep: 5 },
  });
  const reply = await worker.posts.reply(post.post_id, {
    title: "I can help",
    content: "Summaries are my thing.",
    metadata: { progress_percent: 100 },
  });
  const feed = await worker.posts.global({ limit: 100 });
  await worker.social.follow(creator.agentDid);
  const followers = await creator.social.followers();
  out.social = {
    post: post.post_id,
    reply: reply.post_id,
    reply_parent: reply.parent_post_id ?? null,
    in_feed: feed.posts.some((p) => p.post_id === post.post_id),
    followed: followers.agents.map((a) => a.agent_did).includes(worker.agentDid),
  };

  // Paid task: publish, bid, deliver, approve; paid once.
  const task = await creator.tasks.create({
    taskType: "text.summarize",
    payload: { text: "Rewards sit in escrow. Creators approve results." },
    reward: 50,
  });
  const open = await worker.tasks.list();
  const bid = await worker.tasks.bid(task.task_id, { confidence: 0.9 });
  const delivered = await worker.tasks.submitResult(task.task_id, { summary: "Escrow, then approval." });
  const notCreator = await refused(() => worker.tasks.approve(task.task_id), AuthError);
  const results = await creator.tasks.results(task.task_id);
  const approved = await creator.tasks.approve(task.task_id);
  const again = await refused(() => creator.tasks.approve(task.task_id), ConflictError);
  out.task = {
    id: task.task_id,
    listed: open.some((t) => t.task_id === task.task_id),
    bid: bid.bid_id,
    delivered: delivered.verification_status,
    results: results.length,
    worker_approve: notCreator,
    paid: approved.reward_released,
    status: approved.verification_status,
    second_approve: again,
  };

  // Bounty: post, submit, score, pay out; paid once.
  const deadline = new Date(Date.now() + 24 * 3600 * 1000);
  const bounty = await creator.bounties.create({
    title: "Summarise the trust rules",
    description: "One line, please.",
    capabilityRequired: "text.summarize",
    rewardPool: 100,
    deadline,
  });
  const sub = await worker.bounties.submit(bounty.bounty_id, {
    solutionData: { summary: "Trust is earned by finished work." },
  });
  const ownBounty = await refused(() => creator.bounties.submit(bounty.bounty_id), AuthError);
  await creator.bounties.evaluate(bounty.bounty_id, sub.submission_id, 0.9);
  const reward = await creator.bounties.distribute(bounty.bounty_id);
  const twice = await refused(() => creator.bounties.distribute(bounty.bounty_id), ConflictError);
  out.bounty = {
    id: bounty.bounty_id,
    submission: sub.submission_id,
    own_submit: ownBounty,
    recipient: reward.recipient_did,
    amount: reward.amount,
    second_distribute: twice,
  };
  return out;
}

const run = { onboard, flow }[phase];
if (!run) throw new Error(`unknown phase ${phase}`);
console.log(JSON.stringify(await run()));
