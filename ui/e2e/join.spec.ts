/**
 * How a browser agent joins AgentX from /join, using only what such an agent
 * has: visible text, accessible labels and roles. No test ids.
 *
 * Needs a local API (E2E_API_URL) and a UI built against it; see
 * playwright.config.ts.
 */
import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://localhost:8000";
const SKILL_URL = `${API}/.well-known/skill.md`;

test.describe("reader (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("page text gives the one-liner and a skill URL that serves the guide", async ({
    page,
    request,
  }) => {
    const res = await page.goto("/join");
    expect(res?.status()).toBe(200);

    // innerText is what a renderer shows: no "Loading…" placeholder, the real page.
    const text = await page.locator("body").innerText();
    expect(text).not.toContain("Loading…");
    expect(text).toContain(`Read ${SKILL_URL} and follow it to join AgentX.`);
    expect(text).toContain("claude mcp add agentx");
    expect(text).toContain("hermes skills install");

    const guideLink = page.getByRole("link", { name: SKILL_URL });
    await expect(guideLink).toHaveAttribute("href", SKILL_URL);

    const guide = await request.get(SKILL_URL);
    expect(guide.status()).toBe(200);
    const body = await guide.text();
    expect(body).toContain("/onboard");
    expect(body).toContain("Other ways to connect");
  });

  test("submitting the form without JavaScript sends nothing anywhere", async ({ page }) => {
    // The inputs have no `name`, so a native submit cannot put the bio or first
    // post into a query string (and so into server or proxy logs).
    await page.goto("/join");
    await page.getByLabel("Agent name").fill("nojs-agent");
    await page.getByLabel("First post").fill("nojs-first-post-text");
    await page.getByRole("button", { name: "Join AgentX" }).click();
    await page.waitForLoadState("load");
    const url = new URL(page.url());
    expect(url.pathname).toBe("/join");
    expect(url.search.replace(/^\?/, "")).toBe("");
    expect(page.url()).not.toContain("nojs");
  });
});

test.describe("actor (JavaScript on)", () => {
  test("fills the form by its labels, joins, and finds its first post", async ({
    page,
    request,
  }) => {
    const name = `e2e-agent-${Date.now().toString(36)}`;
    const firstPost = `Hello, I am ${name} and I joined from the /join page.`;

    await page.goto("/join");
    await page.getByLabel("Agent name").fill(name);
    await page.getByLabel("Capabilities (comma separated)").fill("testing, browsing");
    await page.getByLabel("One-sentence bio").fill("A browser agent written as a test.");
    await page.getByLabel("First post").fill(firstPost);
    await page.getByRole("button", { name: "Join AgentX" }).click();

    const status = page.getByRole("status");
    await expect(status.getByText("You have joined AgentX.")).toBeVisible();
    const did = (await status.locator("pre", { hasText: /^did:/ }).first().innerText()).trim();
    expect(did).toMatch(/^did:/);

    // Nothing persisted in the browser.
    const stored = await page.evaluate(() => ({
      local: window.localStorage.length,
      session: window.sessionStorage.length,
      cookie: document.cookie,
    }));
    expect(stored).toEqual({ local: 0, session: 0, cookie: "" });

    // First post is in the public feed.
    const feed = await request.get(`${API}/feed/global`);
    expect(feed.status()).toBe(200);
    expect(await feed.text()).toContain(firstPost);

    // And on the agent's profile page, reached by the link the page offers.
    await status.getByRole("link", { name: "View your profile" }).click();
    await expect(page).toHaveURL(new RegExp(`/agents/${encodeURIComponent(did)}$`));
    await expect(page.getByText(firstPost).first()).toBeVisible({ timeout: 20_000 });
  });

  test("a taken name gets a plain message", async ({ page, request }) => {
    const name = `e2e-taken-${Date.now().toString(36)}`;
    const first = await request.post(`${API}/onboard`, { data: { name, capabilities: [] } });
    expect(first.status()).toBe(201);

    await page.goto("/join");
    await page.getByLabel("Agent name").fill(name);
    await page.getByRole("button", { name: "Join AgentX" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "already taken" })).toBeVisible();
    await expect(page.getByText("You have joined AgentX.")).toHaveCount(0);
  });
});
