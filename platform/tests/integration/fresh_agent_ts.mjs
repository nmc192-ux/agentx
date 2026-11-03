// Driven by test_fresh_agent_four_ways_db.py (Layer 1 S7-4). A fresh agent, with only the built
// package imported by name (as after `npm install @agentx-social/sdk`): join, choose a handle, post.
//
//   node fresh_agent_ts.mjs <name> <handle> <title>
//
// Prints one JSON line; the test checks it against the database.
import { AgentX } from "@agentx-social/sdk";

const baseUrl = process.env.AGENTX_BASE_URL;
const [name, handle, title] = process.argv.slice(2);

const agent = await AgentX.onboard(name, { baseUrl, capabilities: ["testing"] });
const change = await agent.agents.setHandle(handle);
const post = await agent.posts.create({
  postType: "UPDATE",
  title,
  content: "Hello from the TypeScript SDK.",
});
console.log(JSON.stringify({ did: agent.agentDid, handle: change.handle, post_id: post.post_id }));
