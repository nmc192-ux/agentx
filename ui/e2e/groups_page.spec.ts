/**
 * A group's page /groups/[id] (Sprint 22, CL-5). The browser's API calls are
 * mocked with page.route; build the UI with NEXT_PUBLIC_FEATURE_COLLECTIVES=true
 * and NEXT_PUBLIC_API_URL=E2E_API_URL pointing at a port with nothing on it,
 * so the server render finds no group and the page reads it in the browser
 * (skipped when the flag is off). Example:
 *   NEXT_PUBLIC_FEATURE_COLLECTIVES=true NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build
 *   npx next start -p 3917 &
 *   E2E_BASE_URL=http://localhost:3917 npx playwright test e2e/groups_page.spec.ts
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://localhost:8000";
const ID = "3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f";
const ME = "did:agentx:tester";
const ASKER = "did:agentx:asker";

const group = {
  collective_id: ID,
  name: "Data Diggers",
  description: "We clean datasets.",
  charter: "Rule one: cite your sources.",
  is_public: true,
  owner_did: "did:agentx:owner",
  member_count: 1,
  trust_score_avg: 0.8,
  created_at: new Date().toISOString(),
  members: [
    {
      agent_did: "did:agentx:owner",
      display_name: "Olive Owner",
      role: "OWNER",
      status: "ACTIVE",
      trust_score: 0.8,
      joined_at: new Date().toISOString(),
    },
  ],
};

const work = {
  collective_id: ID,
  total_tasks: 2,
  counts_by_status: { completed: 1, assigned: 1 },
  tokens_earned: 40,
  tasks: [
    { task_id: "a1", title: "Clean the census file", status: "completed", reward: 50, assigned_at: new Date().toISOString(), tokens_earned: 40 },
    { task_id: "a2", title: "Label the photos", status: "assigned", reward: 30, assigned_at: new Date().toISOString(), tokens_earned: 0 },
  ],
};

test.beforeEach(async ({ request }) => {
  // With the flag off the page redirects home (still a 200 in a streamed page).
  const html = await (await request.get(`/groups/${ID}`)).text();
  test.skip(!html.includes("Loading the group") && !html.includes("Data Diggers"), "UI built without NEXT_PUBLIC_FEATURE_COLLECTIVES=true");
});

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function signIn(page: Page) {
  await page.addInitScript(([did]) => {
    localStorage.setItem("agentx_token", "test-token");
    localStorage.setItem("agentx_did", did);
  }, [ME]);
}

/** Mock the group's reads; `membership` answers GET /membership. */
async function mockGroup(page: Page, membership: { role: string | null; status: string } = { role: null, status: "none" }) {
  await page.route(`${API}/collectives/${ID}`, (r) => json(r, 200, group));
  await page.route(`${API}/collectives/${ID}/work`, (r) => json(r, 200, work));
  await page.route(`${API}/collectives/${ID}/membership`, (r) =>
    json(r, 200, { collective_id: ID, agent_did: ME, since: null, ...membership }),
  );
}

test("signed out: header, charter, members and work done; Ask to join goes to /login", async ({ page }) => {
  let membershipAsked = false;
  await mockGroup(page);
  await page.route(`${API}/collectives/${ID}/membership`, (r) => {
    membershipAsked = true;
    return r.fallback();
  });
  await page.goto(`/groups/${ID}`);
  await expect(page.getByRole("heading", { name: "Data Diggers" })).toBeVisible();
  await expect(page.getByText("Rule one: cite your sources.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Members" }).getByText("Olive Owner")).toBeVisible();
  const done = page.getByRole("region", { name: "Work done" });
  await expect(done.getByText("40 tokens earned")).toBeVisible();
  await expect(done.getByText("Clean the census file")).toBeVisible();
  await expect(page.getByRole("region", { name: "Requests to join" })).toHaveCount(0);
  await page.getByRole("button", { name: "Ask to join" }).click();
  await page.waitForURL(/\/login/);
  expect(new URL(page.url()).searchParams.get("next")).toBe(`/groups/${ID}`);
  expect(membershipAsked).toBe(false);
});

test("Ask to join sends the note with the token, then shows Request sent", async ({ page }) => {
  await signIn(page);
  await mockGroup(page);
  let sent: { auth?: string; body?: unknown } = {};
  await page.route(`${API}/collectives/${ID}/join`, (r) => {
    sent = { auth: r.request().headers()["authorization"], body: r.request().postDataJSON() };
    // From now on the membership read says PENDING.
    void page.route(`${API}/collectives/${ID}/membership`, (m) =>
      json(m, 200, { collective_id: ID, agent_did: ME, role: "MEMBER", status: "PENDING", since: null }),
    );
    return json(r, 202, { status: "pending", collective_id: ID, agent_did: ME });
  });
  await page.goto(`/groups/${ID}`);
  await page.getByRole("button", { name: "Ask to join" }).click();
  await page.getByLabel(/A note for the group/).fill("  I clean CSVs fast. ");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Request sent.")).toBeVisible();
  expect(sent.auth).toBe("Bearer test-token");
  expect(sent.body).toEqual({ message: "I clean CSVs fast." });
});

test("a refused join shows the API's text", async ({ page }) => {
  await signIn(page);
  await mockGroup(page);
  await page.route(`${API}/collectives/${ID}/join`, (r) => json(r, 404, { detail: `Collective not found: ${ID}` }));
  await page.goto(`/groups/${ID}`);
  await page.getByRole("button", { name: "Ask to join" }).click();
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("region", { name: "Membership" }).getByRole("alert")).toHaveText(
    `Collective not found: ${ID}`,
  );
});

test("a member can leave (DELETE on their own DID)", async ({ page }) => {
  await signIn(page);
  await mockGroup(page, { role: "MEMBER", status: "ACTIVE" });
  let deleted = "";
  await page.route(`${API}/collectives/${ID}/members/**`, (r) => {
    if (r.request().method() !== "DELETE") return r.fallback();
    deleted = new URL(r.request().url()).pathname;
    void page.route(`${API}/collectives/${ID}/membership`, (m) =>
      json(m, 200, { collective_id: ID, agent_did: ME, role: null, status: "none", since: null }),
    );
    return r.fulfill({ status: 204 });
  });
  page.on("dialog", (d) => d.accept());
  await page.goto(`/groups/${ID}`);
  await expect(page.getByText("You are a member of this group.")).toBeVisible();
  await page.getByRole("button", { name: "Leave" }).click();
  await expect(page.getByRole("button", { name: "Ask to join" })).toBeVisible();
  expect(decodeURIComponent(deleted)).toBe(`/collectives/${ID}/members/${ME}`);
});

test("the owner sees pending requests with the note and can approve", async ({ page }) => {
  await signIn(page);
  await mockGroup(page, { role: "OWNER", status: "ACTIVE" });
  let pending = [
    { agent_did: ASKER, display_name: "Ada Asker", trust_score: 0.5, requested_at: new Date().toISOString(), message: "Let me in, I label fast." },
  ];
  await page.route(`${API}/collectives/${ID}/requests`, (r) => json(r, 200, pending));
  let approved = "";
  await page.route(`${API}/collectives/${ID}/members/**`, (r) => {
    approved = new URL(r.request().url()).pathname;
    pending = [];
    return json(r, 200, { status: "approved" });
  });
  await page.goto(`/groups/${ID}`);
  await expect(page.getByText("You own this group.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Leave" })).toHaveCount(0);
  const box = page.getByRole("region", { name: "Requests to join" });
  await expect(box.getByText("Let me in, I label fast.")).toBeVisible();
  await box.getByRole("button", { name: "Approve Ada Asker" }).click();
  await expect(box.getByText("No one is waiting.")).toBeVisible();
  expect(decodeURIComponent(approved)).toBe(`/collectives/${ID}/members/${ASKER}/approve`);
});

test("a plain member sees no requests and never asks for them", async ({ page }) => {
  await signIn(page);
  await mockGroup(page, { role: "MEMBER", status: "ACTIVE" });
  let asked = false;
  await page.route(`${API}/collectives/${ID}/requests`, (r) => {
    asked = true;
    return json(r, 403, { detail: "no" });
  });
  await page.goto(`/groups/${ID}`);
  await expect(page.getByText("You are a member of this group.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Requests to join" })).toHaveCount(0);
  expect(asked).toBe(false);
});

test("a group the API will not show is 'Group not found'", async ({ page }) => {
  await page.route(`${API}/collectives/${ID}`, (r) => json(r, 404, { detail: "Collective not found" }));
  await page.route(`${API}/collectives/${ID}/work`, (r) => json(r, 404, { detail: "Collective not found" }));
  await page.goto(`/groups/${ID}`);
  await expect(page.getByRole("heading", { name: "Group not found" })).toBeVisible();
});
