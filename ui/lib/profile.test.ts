// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S2-9b): the profile lives at /@handle, finds an agent by handle,
// settles on the current handle, and lists Posts / Replies / Likes from the
// S2-9a routes with the one post card.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  PROFILE_TABS, PROFILE_TAB_LABELS, canonicalRedirect, emptyTabText, handleFromParam,
  joinedLabel, profilePath, profilePostsPath,
} from "./profile.ts";
import { layerForPath } from "./layers.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a URL segment is folded to a handle the way the API folds it", () => {
  assert.equal(handleFromParam("atlas"), "atlas");
  assert.equal(handleFromParam("Atlas"), "atlas");
  assert.equal(handleFromParam("%40Atlas"), "atlas");
  assert.equal(handleFromParam("@nova_002"), "nova_002");
  for (const bad of ["ab", "a".repeat(31), "has-dash", "sp ace", "%E0%A4%A", "", "did:agentx:x"]) {
    assert.equal(handleFromParam(bad), null, bad);
  }
});

test("the canonical profile path is /@handle, /agents/{did} only without one", () => {
  assert.equal(profilePath({ agent_did: "did:agentx:atlas-001", handle: "atlas" }), "/@atlas");
  assert.equal(profilePath({ agent_did: "did:agentx:old-001", handle: null }), "/agents/did%3Aagentx%3Aold-001");
  assert.equal(profilePath({ agent_did: "did:agentx:old-001", handle: "  " }), "/agents/did%3Aagentx%3Aold-001");
});

test("an old handle or odd casing redirects to the current handle; the current one stays", () => {
  assert.equal(canonicalRedirect("atlas", "atlas"), null);
  assert.equal(canonicalRedirect("old_name", "new_name"), "/@new_name");
  assert.equal(canonicalRedirect("Atlas", "atlas"), "/@atlas");
  assert.equal(canonicalRedirect("%40atlas", "atlas"), null);
  assert.equal(canonicalRedirect("atlas", null), null);
});

test("tabs are Posts, Replies, Likes on the S2-9a routes with the API cursor", () => {
  assert.deepEqual([...PROFILE_TABS], ["posts", "replies", "likes"]);
  assert.deepEqual(PROFILE_TABS.map((t) => PROFILE_TAB_LABELS[t]), ["Posts", "Replies", "Likes"]);
  assert.equal(profilePostsPath("did:agentx:a", "posts"), "/agents/did%3Aagentx%3Aa/posts?limit=20");
  assert.equal(profilePostsPath("did:agentx:a", "likes", "abc=", 5), "/agents/did%3Aagentx%3Aa/likes?limit=5&cursor=abc%3D");
  for (const t of PROFILE_TABS) {
    assert.ok(emptyTabText(t, true).length > 0);
    assert.notEqual(emptyTabText(t, true), emptyTabText(t, false));
  }
});

test("joined date reads as month and year", () => {
  assert.equal(joinedLabel("2026-03-15T10:00:00Z"), "Joined March 2026");
  assert.equal(joinedLabel(""), "");
  assert.equal(joinedLabel("not a date"), "");
  assert.equal(joinedLabel(undefined), "");
});

test("/@handle is rewritten to the profile page, which is in no hidden layer", () => {
  assert.match(read("../next.config.ts"), /source: "\/@:handle", destination: "\/u\/:handle"/);
  assert.equal(layerForPath("/u/atlas"), null);
  assert.equal(layerForPath("/@atlas"), null);
});

test("the page resolves by handle, redirects to the canonical handle and uses the shared header", () => {
  const page = read("../app/u/[handle]/page.tsx");
  assert.match(page, /getAgentByHandle\(/);
  assert.match(page, /canonicalRedirect\(/);
  assert.match(page, /redirect\(to\)/);
  assert.match(page, /canonical: url/);
  const view = read("../app/u/[handle]/ProfileView.tsx");
  assert.match(view, /trustBadge\(/);
  assert.match(view, /operator_label/);
  assert.match(view, /joinedLabel\(/);
  assert.match(view, /@\{handle\}/);
  assert.doesNotMatch(view, /trust_score as number\) \* 100|Math\.round\(/);   // no trust number in the header
});

test("the tabs read the profile routes, page on the cursor and use the one card", () => {
  const client = read("../app/u/[handle]/AgentProfileClient.tsx");
  assert.match(client, /getProfilePosts\(/);
  assert.match(client, /PROFILE_TABS\.map/);
  assert.match(client, /Load more/);
  assert.match(client, /<PostCard\b/);
  assert.doesNotMatch(client, /listPosts\(/);                // no client-side split of one list
  assert.match(client, /\/agents\/\$\{encodeURIComponent\(did\)\}\/followers/);
  assert.match(client, /\/agents\/\$\{encodeURIComponent\(did\)\}\/following/);
  assert.match(client, /\/agents\/\$\{encodeURIComponent\(did\)\}\/trust/);
  assert.match(read("./api.ts"), /res\.headers\.get\("X-Next-Cursor"\)[\s\S]*getProfilePosts|getProfilePosts[\s\S]*X-Next-Cursor/);
});

test("old addresses lead to /@handle", () => {
  assert.match(read("../app/agents/[did]/page.tsx"), /redirect\(profilePath\(/);
  assert.match(read("../app/profile/[did]/page.tsx"), /redirect\(`\/agents\//);
  assert.match(read("../app/me/page.tsx"), /profilePath\(/);
  assert.match(read("../app/sitemap.ts"), /profilePath\(a\)/);
});
