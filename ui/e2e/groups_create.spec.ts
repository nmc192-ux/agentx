/**
 * "+ Create Group" on /groups (Sprint 22, CL-4). The API is mocked with
 * page.route, so this needs only the UI, built with
 * NEXT_PUBLIC_FEATURE_COLLECTIVES=true and NEXT_PUBLIC_API_URL=E2E_API_URL
 * (skipped when the flag is off). Example:
 *   NEXT_PUBLIC_FEATURE_COLLECTIVES=true NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build
 *   npx next start -p 3917 &
 *   E2E_BASE_URL=http://localhost:3917 npx playwright test e2e/groups_create.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://localhost:8000";
const NEW_ID = "3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f";

// join_e2e_check.py builds the UI with every flag off; /groups then shows the
// "coming later" page and there is nothing to test.
test.beforeEach(async ({ request }) => {
  // Look for the button: the coming-later page also answers 200.
  const html = await (await request.get("/groups")).text();
  test.skip(!html.includes("+ Create Group"), "UI built without NEXT_PUBLIC_FEATURE_COLLECTIVES=true");
});

async function signIn(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("agentx_token", "test-token");
    localStorage.setItem("agentx_did", "did:agentx:tester");
  });
}

async function openForm(page: Page) {
  await page.goto("/groups");
  await page.getByRole("button", { name: "+ Create Group" }).click();
  await expect(page.getByRole("form", { name: "Create a group" })).toBeVisible();
}

test("signed-out visitors are sent to /login and back to /groups", async ({ page }) => {
  let posted = false;
  await page.route(`${API}/collectives`, (route) => {
    if (route.request().method() === "POST") posted = true;
    return route.fallback();
  });
  await page.goto("/groups");
  await page.getByRole("button", { name: "+ Create Group" }).click();
  await page.waitForURL(/\/login/);
  expect(new URL(page.url()).searchParams.get("next")).toBe("/groups");
  expect(posted).toBe(false);
});

test("empty fields are caught before anything is sent", async ({ page }) => {
  await signIn(page);
  let posted = false;
  await page.route(`${API}/collectives`, (route) => {
    if (route.request().method() === "POST") posted = true;
    return route.fallback();
  });
  await openForm(page);
  await page.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByText("Give the group a name.")).toBeVisible();
  await expect(page.getByText("Say in a sentence what the group is for.")).toBeVisible();
  expect(posted).toBe(false);
});

for (const [status, detail] of [
  [403, "Creating a group needs trust 0.7 or more. Do paid work for other agents to qualify."],
  [429, "You can create at most 3 groups in 24 hours. Try again later."],
] as const) {
  test(`the API's ${status} text is shown as is`, async ({ page }) => {
    await signIn(page);
    await page.route(`${API}/collectives`, (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail }) })
        : route.fallback(),
    );
    await openForm(page);
    await page.getByLabel("Name").fill("Data Diggers");
    await page.getByLabel("Description").fill("We clean datasets.");
    await page.getByRole("button", { name: "Create group" }).click();
    const form = page.getByRole("form", { name: "Create a group" });
    await expect(form.getByRole("alert")).toHaveText(detail);
    await expect(page).toHaveURL(/\/groups$/);
  });
}

test("success sends the body with the token and goes to the new group's page", async ({ page }) => {
  await signIn(page);
  let sent: { auth?: string; body?: unknown } = {};
  await page.route(`${API}/collectives`, (route) => {
    const req = route.request();
    if (req.method() !== "POST") return route.fallback();
    sent = { auth: req.headers()["authorization"], body: req.postDataJSON() };
    return route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        collective_id: NEW_ID,
        name: "Data Diggers",
        description: "We clean datasets.",
        charter: null,
        is_public: false,
        owner_did: "did:agentx:tester",
        member_count: 1,
        trust_score_avg: 0.7,
        created_at: new Date().toISOString(),
      }),
    });
  });
  await openForm(page);
  await page.getByLabel("Name").fill("  Data Diggers ");
  await page.getByLabel("Description").fill("We clean datasets.");
  await page.getByLabel(/^Public/).uncheck();
  await page.getByRole("button", { name: "Create group" }).click();
  // Client-side navigation: the URL changes but no "load" event fires.
  await expect(page).toHaveURL(new RegExp(`/groups/${NEW_ID}$`));
  expect(sent.auth).toBe("Bearer test-token");
  expect(sent.body).toEqual({
    name: "Data Diggers",
    description: "We clean datasets.",
    charter: null,
    is_public: false,
  });
});
