// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S4-10a2: attaching images in the composer. The attach button
// shows only when GET /media/settings says uploads are on; picked files are
// checked against the server's limits; images upload when the post is sent
// and the post names them in media_ids.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  acceptAttr, altProblem, canAttach, fileProblem, hasBody, needsUpload, parseMediaSettings,
  pickFiles, uploadAll, uploadErrorText, type Attachment, type MediaSettings,
} from "./composerMedia.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const IMAGES = read("../components/feed/ComposerImages.tsx");
const COMPOSE = read("../components/feed/SocialComposeBox.tsx");
const QUOTE = read("../components/feed/QuoteModal.tsx");
const API = read("./api.ts");
const TYPES = read("../types.ts");
const ROUTER = read("../../platform/src/routers/media.py");
const IMAGES_PY = read("../../platform/src/services/media_images.py");
const MODELS = read("../../platform/src/models/post.py");

const ON: MediaSettings = {
  media_enabled: true, link_cards_enabled: false, max_images: 4,
  max_bytes: 5 * 1024 * 1024, max_alt_text: 1000,
  mimes: ["image/gif", "image/jpeg", "image/png", "image/webp"],
};
const file = (name: string, type = "image/png", size = 1000) => ({ name, type, size });
const att = (key: string, over: Partial<Attachment> = {}): Attachment => ({
  key, file: new Blob(["x"]), name: key, previewUrl: `blob:${key}`, alt: "", ...over,
});

test("parseMediaSettings accepts the server's body and treats anything odd as off", () => {
  assert.deepEqual(parseMediaSettings({ ...ON }), ON);
  for (const bad of [
    null, undefined, "on", 1, [], {},
    { ...ON, media_enabled: "true" },
    { ...ON, link_cards_enabled: undefined },
    { ...ON, max_images: 0 }, { ...ON, max_images: 2.5 }, { ...ON, max_bytes: "5" },
    { ...ON, max_alt_text: -1 }, { ...ON, mimes: "image/png" },
    { ...ON, mimes: ["text/html"] }, { ...ON, mimes: [1] },
  ]) {
    assert.equal(parseMediaSettings(bad), null, JSON.stringify(bad));
  }
});

test("the attach button needs uploads on and room for another image", () => {
  assert.equal(canAttach(null, 0), false);
  assert.equal(canAttach({ ...ON, media_enabled: false }, 0), false);
  assert.equal(canAttach(ON, 0), true);
  assert.equal(canAttach(ON, 3), true);
  assert.equal(canAttach(ON, 4), false);
  assert.equal(acceptAttr(ON), "image/gif,image/jpeg,image/png,image/webp");
  assert.equal(acceptAttr(null), "");
});

test("fileProblem refuses other types, empty and oversized files in plain words", () => {
  assert.equal(fileProblem(file("a.png"), ON), null);
  assert.equal(fileProblem(file("a.jpg", "image/jpeg", ON.max_bytes), ON), null);
  assert.match(fileProblem(file("a.svg", "image/svg+xml"), ON) ?? "", /a\.svg is not a JPEG, PNG, WebP or GIF/);
  assert.match(fileProblem(file("a.html", "text/html"), ON) ?? "", /not a JPEG/);
  assert.match(fileProblem(file("a.png", ""), ON) ?? "", /not a JPEG/);
  assert.match(fileProblem(file("a.png", "image/png", 0), ON) ?? "", /a\.png is empty/);
  assert.match(fileProblem(file("big.png", "image/png", ON.max_bytes + 1), ON) ?? "", /big\.png is larger than 5 MB/);
});

test("pickFiles keeps at most max_images in total and says what was left out", () => {
  const five = [1, 2, 3, 4, 5].map((n) => file(`${n}.png`));
  let r = pickFiles(five, 0, ON);
  assert.deepEqual(r.accepted.map((f) => f.name), ["1.png", "2.png", "3.png", "4.png"]);
  assert.deepEqual(r.problems, ["At most 4 images per post; 1 not added."]);

  r = pickFiles([file("a.png"), file("b.txt", "text/plain"), file("c.png")], 3, ON);
  assert.deepEqual(r.accepted.map((f) => f.name), ["a.png"]);
  assert.equal(r.problems.length, 2);
  assert.match(r.problems[0], /b\.txt is not/);
  assert.match(r.problems[1], /1 not added/);

  r = pickFiles([file("a.png")], 4, ON);
  assert.deepEqual(r.accepted, []);
  assert.deepEqual(pickFiles([], 0, ON), { accepted: [], problems: [] });
});

test("alt text is optional and bounded; a post needs text or an image", () => {
  assert.equal(altProblem("", ON), null);
  assert.equal(altProblem("x".repeat(1000), ON), null);
  assert.equal(altProblem(`  ${"x".repeat(1000)}  `, ON), null);
  assert.match(altProblem("x".repeat(1001), ON) ?? "", /over 1000 characters/);
  assert.equal(hasBody("", []), false);
  assert.equal(hasBody("   ", []), false);
  assert.equal(hasBody("hi", []), true);
  assert.equal(hasBody("", [att("a")]), true);
});

test("an image is re-uploaded only when it has no id or its alt text changed", () => {
  assert.equal(needsUpload(att("a")), true);
  assert.equal(needsUpload(att("a", { mediaId: "m", uploadedAlt: "" })), false);
  assert.equal(needsUpload(att("a", { mediaId: "m", uploadedAlt: "cat", alt: " cat " })), false);
  assert.equal(needsUpload(att("a", { mediaId: "m", uploadedAlt: "cat", alt: "dog" })), true);
});

function recorder(items: Attachment[]) {
  const state = new Map(items.map((a) => [a.key, { ...a }]));
  const log: string[] = [];
  const update = (key: string, patch: Partial<Attachment>) => {
    state.set(key, { ...(state.get(key) as Attachment), ...patch });
    log.push(`${key}:${Object.keys(patch).join(",")}`);
  };
  return { state, log, update };
}

test("uploadAll uploads in order, reports progress and returns the ids", async () => {
  const items = [att("a", { alt: " first " }), att("b", { mediaId: "kept", uploadedAlt: "" }), att("c")];
  const { state, update } = recorder(items);
  const sent: string[] = [];
  const ids = await uploadAll(items, async (_f, alt, onProgress) => {
    sent.push(alt);
    onProgress(50);
    onProgress(100);
    return { media_id: `id-${sent.length}` };
  }, update);
  assert.deepEqual(ids, ["id-1", "kept", "id-2"]);
  assert.deepEqual(sent, ["first", ""]);
  assert.equal(state.get("a")?.mediaId, "id-1");
  assert.equal(state.get("a")?.uploadedAlt, "first");
  assert.equal(state.get("a")?.progress, undefined);
  assert.equal(state.get("c")?.mediaId, "id-2");
});

test("uploadAll stops at the first failure and marks only that image", async () => {
  const items = [att("a"), att("b"), att("c")];
  const { state, update } = recorder(items);
  let calls = 0;
  const ids = await uploadAll(items, async () => {
    calls += 1;
    if (calls === 2) throw Object.assign(new Error("x"), { status: 415 });
    return { media_id: `id-${calls}` };
  }, update);
  assert.equal(ids, null);
  assert.equal(calls, 2);
  assert.equal(state.get("a")?.mediaId, "id-1");
  assert.equal(state.get("b")?.error, uploadErrorText(415));
  assert.equal(state.get("b")?.progress, undefined);
  assert.equal(state.get("c")?.error, undefined);

  // The retry sends only what is still missing.
  const retry = [state.get("a") as Attachment, { ...(state.get("b") as Attachment) }, state.get("c") as Attachment];
  const again = recorder(retry);
  const sent: string[] = [];
  const ids2 = await uploadAll(retry, async () => {
    sent.push("x");
    return { media_id: `new-${sent.length}` };
  }, again.update);
  assert.deepEqual(ids2, ["id-1", "new-1", "new-2"]);
  assert.equal(again.state.get("b")?.error, undefined);
});

test("upload errors are plain words for every status the server sends", () => {
  for (const s of [0, 401, 404, 413, 415, 422, 429, 507, 500, -1]) {
    const text = uploadErrorText(s);
    assert.ok(text.length > 10 && !/\{|undefined|null/.test(text), `${s}: ${text}`);
  }
  assert.match(uploadErrorText(404), /switched off/);
  assert.match(uploadErrorText(413), /too large/);
  assert.match(uploadErrorText(429), /50 a day/);
});

test("limits and types agree with the server", () => {
  assert.match(MODELS, /^MAX_POST_MEDIA = 4$/m);
  assert.match(ROUTER, /^MAX_ALT_TEXT = 1000$/m);
  assert.match(IMAGES_PY, /^MAX_INPUT_BYTES = 5 \* 1024 \* 1024/m);
  for (const m of ON.mimes) assert.ok(IMAGES_PY.includes(`"${m}"`), m);
  // GET /media/settings is registered before GET /media/{media_id}.
  assert.ok(ROUTER.indexOf('"/settings"') > 0);
  assert.ok(ROUTER.indexOf('"/settings"') < ROUTER.indexOf('"/{media_id}"'));
});

test("api: settings once per page, failures mean off; upload is multipart with the token", () => {
  assert.match(API, /request<unknown>\("GET", "\/media\/settings"\)/);
  assert.match(API, /\.then\(parseMediaSettings\)/);
  assert.match(API, /\.catch\(\(\) => \{\s*mediaSettingsPromise = null;\s*return null;/);
  assert.match(API, /form\.append\("file", file\)/);
  assert.match(API, /form\.append\("alt_text", altText\)/);
  assert.match(API, /xhr\.open\("POST", `\$\{BASE\}\/media`\)/);
  assert.match(API, /setRequestHeader\("Authorization", `Bearer \$\{token\}`\)/);
  assert.match(TYPES, /media_ids\?: string\[\];/);
});

test("composer and quote modal: hidden while off, upload before posting, media_ids sent", () => {
  assert.match(IMAGES, /if \(!images\.settings\?\.media_enabled\) return null;/);
  assert.match(IMAGES, /if \(!settings\?\.media_enabled \|\| /);
  assert.match(IMAGES, /URL\.revokeObjectURL/);
  assert.match(IMAGES, /accept=\{acceptAttr\(images\.settings\)\}/);
  assert.match(IMAGES, /role="progressbar"/);
  assert.match(IMAGES, /maxLength=\{settings\.max_alt_text\}/);
  for (const [name, src] of [["compose", COMPOSE], ["quote", QUOTE]] as const) {
    assert.match(src, /useComposerImages\(\)/, name);
    assert.match(src, /<ComposerImageButton images=\{images\}/, name);
    assert.match(src, /<ComposerImageList images=\{images\}/, name);
    assert.match(src, /hasBody\(content, images\.items\)/, name);
    assert.match(src, /!images\.altError/, name);
    const upload = src.indexOf("await images.upload(token)");
    const create = src.indexOf("await createPost(");
    assert.ok(upload > 0 && upload < create, `${name}: uploads before the post`);
    assert.match(src, /media_ids: mediaIds/, name);
    assert.match(src, /images\.clear\(\)/, name);
  }
  // The hook is called before the composer's logged-out early return.
  assert.ok(COMPOSE.indexOf("useComposerImages()") < COMPOSE.indexOf("if (!loggedIn) return null"));
});
