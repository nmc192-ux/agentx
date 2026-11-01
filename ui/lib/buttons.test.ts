// Run with `npm test`. Layer 1 (S1-5): no button on a visible page does nothing.
// React handlers are invisible in the rendered page, so the dead-end crawl
// (e2e/dead_ends.spec.ts) can't see them; this reads the source instead.
// Every <button> must have onClick (or a pointer/mouse handler), be a form
// submit, or take spread props from its caller. Pages in a hidden layer are
// skipped until that layer opens.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { test } from "node:test";

import { layerForPath } from "./layers.ts";

const ROOT = join(import.meta.dirname, "..");

/** Components with known dead buttons, used only by hidden pages. */
const HIDDEN_ONLY: Record<string, string> = {
  "components/marketplace/BountyCard.tsx": "'Claim Bounty' has no handler; fix when markets open",
};

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return tsxFiles(p);
    return p.endsWith(".tsx") ? [p] : [];
  });
}

/** "/markets" for app/markets/page.tsx, "/agents/[did]" for app/agents/[did]/X.tsx. */
function routeOf(file: string): string | null {
  if (!file.startsWith("app/")) return null;
  const parts = file.split("/").slice(1, -1).filter((s) => !/^\(.*\)$/.test(s));
  return "/" + parts.join("/");
}

function isHiddenRoute(file: string): boolean {
  const route = routeOf(file);
  return route !== null && route !== "/" && layerForPath(route) !== null;
}

function stripComments(src: string): string {
  return src.replace(/\{\/\*[\s\S]*?\*\/\}/g, "").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** The attribute text of each <button ...> tag, reading past `>` inside {braces}. */
function buttonTags(src: string): { attrs: string; index: number }[] {
  const out: { attrs: string; index: number }[] = [];
  for (const m of src.matchAll(/<button\b/g)) {
    let depth = 0;
    let i = m.index + m[0].length;
    for (; i < src.length; i++) {
      const c = src[i];
      if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0) break;
    }
    out.push({ attrs: src.slice(m.index + m[0].length, i), index: m.index });
  }
  return out;
}

const files = [...tsxFiles(join(ROOT, "app")), ...tsxFiles(join(ROOT, "components"))].map((f) =>
  relative(ROOT, f),
);

test("every button on a visible page has something to do", () => {
  const dead: string[] = [];
  for (const file of files) {
    if (isHiddenRoute(file) || file in HIDDEN_ONLY) continue;
    const src = stripComments(readFileSync(join(ROOT, file), "utf8"));
    for (const { attrs, index } of buttonTags(src)) {
      if (/\bon(Click|MouseDown|PointerDown)=|type=["{]*["']?submit|\{\s*\.\.\./.test(attrs)) continue;
      const line = src.slice(0, index).split("\n").length;
      dead.push(`${file}:${line}`);
    }
  }
  assert.deepEqual(dead, []);
});

test("components with known dead buttons are only used by hidden pages", () => {
  for (const comp of Object.keys(HIDDEN_ONLY)) {
    const name = comp.split("/").pop()!.replace(/\.tsx$/, "");
    const users = files.filter(
      (f) => f !== comp && new RegExp(`from ["'][^"']*/${name}["']`).test(readFileSync(join(ROOT, f), "utf8")),
    );
    assert.ok(users.length > 0, `${comp} is unused; drop it from HIDDEN_ONLY`);
    for (const u of users) assert.ok(isHiddenRoute(u), `${comp} is used by visible ${u}`);
  }
});

test("the tag reader reads past arrow functions", () => {
  const [tag] = buttonTags(`<button onMouseEnter={() => x()} onClick={go}>Hi</button>`);
  assert.match(tag.attrs, /onClick=\{go\}/);
});

test("the hidden-route check knows a hidden page from a visible one", () => {
  assert.equal(isHiddenRoute("app/markets/page.tsx"), true);
  assert.equal(isHiddenRoute("app/rooms/[id]/page.tsx"), true);
  assert.equal(isHiddenRoute("app/agents/[did]/AgentProfileClient.tsx"), false);
  assert.equal(isHiddenRoute("app/page.tsx"), false);
  assert.equal(isHiddenRoute("components/feed/PostCard.tsx"), false);
});
