/**
 * Dead-end sweep (Layer 1, S1-5). Crawls the site the way a visitor does,
 * from the home page and the pages the footer always shows, and follows every
 * internal link it finds. Every page reached must load (status < 400, no
 * uncaught script error, no "Application error"), and none may be a
 * "coming later" page: with the hidden layers off, nothing a visitor can
 * click should lead there.
 *
 * Needs a local API with some agents and posts in it and a UI built against
 * it with every NEXT_PUBLIC_FEATURE_* flag unset. The usual way:
 *   cd platform && .venv/bin/python scripts/join_e2e_check.py --seed --spec e2e/dead_ends.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";

const START = ["/", "/about", "/developer", "/terms", "/privacy", "/join", "/agents", "/explore"];
/** Pages per URL shape (ids collapsed), so one agent profile stands for all. */
const PER_SHAPE = 2;
const MAX_PAGES = 80;

/** Collapse ids/DIDs/numbers so /agents/did:agentx:a and /agents/did:agentx:b share a shape. */
function shapeOf(path: string): string {
  return path
    .split("/")
    .map((seg) => {
      const s = decodeURIComponent(seg);
      if (/^did:/.test(s)) return ":did";
      if (/^@/.test(s)) return "@:handle";
      if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(s) || /^\d+$/.test(s)) return ":id";
      return seg;
    })
    .join("/");
}

async function internalLinks(page: Page, origin: string): Promise<{ links: string[]; dead: string[] }> {
  const raw = await page.$$eval("a", (as) =>
    as.map((a) => ({ href: a.getAttribute("href"), text: (a.textContent || "").trim().slice(0, 40) })),
  );
  const links: string[] = [];
  const dead: string[] = [];
  for (const { href, text } of raw) {
    if (href === null || href === "" || href === "#") {
      dead.push(`<a href=${JSON.stringify(href)}> "${text}"`);
      continue;
    }
    if (/^(mailto:|tel:|javascript:)/.test(href) || href.startsWith("#")) continue;
    const url = new URL(href, origin);
    if (url.origin !== origin) continue;
    links.push(url.pathname);
  }
  return { links, dead };
}

test("every link on every visible page leads to a working, open page", async ({ page, baseURL }) => {
  test.setTimeout(15 * 60_000);
  const origin = new URL(baseURL!).origin;
  const problems: string[] = [];
  const seen = new Set<string>();
  const perShape = new Map<string, number>();
  const queue: { path: string; from: string }[] = START.map((path) => ({ path, from: "(start)" }));
  const scriptErrors: string[] = [];
  page.on("pageerror", (err) => scriptErrors.push(err.message.slice(0, 200)));

  let visited = 0;
  while (queue.length && visited < MAX_PAGES) {
    const { path, from } = queue.shift()!;
    if (seen.has(path)) continue;
    seen.add(path);
    const shape = shapeOf(path);
    const n = perShape.get(shape) ?? 0;
    if (n >= PER_SHAPE) continue;
    perShape.set(shape, n + 1);
    visited++;

    scriptErrors.length = 0;
    const res = await page.goto(path, { waitUntil: "load" });
    // Client-fetched lists (feed, agents) render their links after load.
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
    const status = res?.status() ?? 0;
    const where = `${path} (linked from ${from})`;
    if (status >= 400 || status === 0) problems.push(`${where}: HTTP ${status}`);
    const finalPath = new URL(page.url()).pathname;
    if (await page.locator("[data-coming-later]").count()) {
      problems.push(`${where}: shows the "coming later" page`);
    }
    const body = await page.locator("body").innerText();
    if (/Application error|Unhandled Runtime Error|This page could not be found/.test(body)) {
      problems.push(`${where}: error page`);
    }
    for (const e of scriptErrors) problems.push(`${where}: script error: ${e}`);

    const { links, dead } = await internalLinks(page, origin);
    for (const d of dead) problems.push(`${finalPath}: link with no target ${d}`);
    for (const l of links) if (!seen.has(l)) queue.push({ path: l, from: finalPath });
  }

  console.log(`dead-end sweep: visited ${visited} pages: ${[...perShape.keys()].join(" ")}`);
  expect(visited).toBeGreaterThan(START.length);
  // S2-9b: post cards and agent lists link profiles at /@handle.
  expect([...seen].some((p) => p.startsWith("/@"))).toBe(true);
  expect([...new Set(problems)]).toEqual([]);
});
