/**
 * Economy counters page /stats/economy (Sprint 23, EM-2). The page reads
 * GET /stats/economy on the server, so this spec runs its own stand-in API
 * on E2E_API_URL's port and the UI must be built with NEXT_PUBLIC_API_URL
 * pointing there. Example:
 *   NEXT_PUBLIC_FEATURE_ECONOMY=true NEXT_PUBLIC_API_URL=http://localhost:8917 npm run build
 *   npx next start -p 3917 &
 *   E2E_BASE_URL=http://localhost:3917 E2E_API_URL=http://localhost:8917 npx playwright test e2e/economy_stats.spec.ts
 * Built with the flag off, only the "flag off" test runs (the page is the
 * not-found page and the API is never asked).
 */
import { createServer, type Server } from "node:http";
import { expect, test } from "@playwright/test";

const API = new URL(process.env.E2E_API_URL || "http://localhost:8917");

const stats = {
  bounties_posted: { count: 3, target: 10 },
  bounties_paid: { count: 5, target: 5 },
  collectives_by_outsiders: { count: 1, target: 3 },
  outside_agents_joined: { count: 1234, target: 100 },
  outside_agents_posting: { count: 40, target: 100 },
  outside_agents_trusted: { count: 0, target: 1 },
  as_of: "2026-10-15T03:29:00+00:00",
};

let reply: { status: number; body: unknown } = { status: 200, body: stats };
let asked = 0;
let server: Server;

test.beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url?.startsWith("/stats/economy")) {
      asked += 1;
      res.writeHead(reply.status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(reply.body));
      return;
    }
    // Everything else the layout may ask for: nothing there.
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: "Not Found" }));
  });
  await new Promise<void>((resolve) => server.listen(Number(API.port), API.hostname, resolve));
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

test.beforeEach(() => {
  reply = { status: 200, body: stats };
  asked = 0;
});

// With the flag off the page is the "coming later" page (Layer 1, S1-1).
async function flagOn(request: import("@playwright/test").APIRequestContext) {
  const html = await (await request.get("/stats/economy")).text();
  return !html.includes("data-coming-later=");
}

test("shows each counter as n of target, with the time counted", async ({ page, request }) => {
  test.skip(!(await flagOn(request)), "UI built without NEXT_PUBLIC_FEATURE_ECONOMY=true");
  await page.goto("/stats/economy", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Economy counters" })).toBeVisible();
  const card = (key: string) => page.locator(`[data-counter="${key}"]`);
  await expect(card("bounties_posted")).toContainText("3 of 10");
  await expect(card("bounties_paid")).toContainText("5 of 5");
  await expect(card("bounties_paid")).toContainText("goal met");
  await expect(card("bounties_posted")).not.toContainText("goal met");
  await expect(card("collectives_by_outsiders")).toContainText("Groups formed");
  await expect(card("outside_agents_joined")).toContainText("1,234 of 100");
  await expect(card("outside_agents_trusted")).toContainText("0 of 1");
  await expect(page.locator("[data-counter]")).toHaveCount(6);
  await expect(page.getByText("Counted at 15 Oct 2026, 03:29 UTC")).toBeVisible();
  expect(asked).toBeGreaterThan(0);
});

test("API switched off (404) shows the switched-off message", async ({ page, request }) => {
  test.skip(!(await flagOn(request)), "UI built without NEXT_PUBLIC_FEATURE_ECONOMY=true");
  reply = { status: 404, body: { detail: "Not Found" } };
  await page.goto("/stats/economy", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("The counters are switched off")).toBeVisible();
  await expect(page.locator("[data-counter]")).toHaveCount(0);
});

test("API failing (503) says the numbers are unavailable", async ({ page, request }) => {
  test.skip(!(await flagOn(request)), "UI built without NEXT_PUBLIC_FEATURE_ECONOMY=true");
  reply = { status: 503, body: { detail: "Founder roster is misconfigured" } };
  await page.goto("/stats/economy", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("The counters are not available right now")).toBeVisible();
  await expect(page.locator("[data-counter]")).toHaveCount(0);
});

test("flag off: the page says coming later and the API is never asked", async ({ page, request }) => {
  test.skip(await flagOn(request), "UI built with NEXT_PUBLIC_FEATURE_ECONOMY=true");
  await page.goto("/stats/economy", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Coming later")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Markets and tasks" })).toBeVisible();
  await expect(page.locator("[data-counter]")).toHaveCount(0);
  await expect(page.locator('footer a[href="/stats/economy"]')).toHaveCount(0);
  expect(asked).toBe(0);
});
