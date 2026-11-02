// Layer 1 (S3-8a): which parts of a post's text are links. A plain function,
// so `linkify.test.ts` pins the rules without a browser; `text/richText.tsx`
// turns the segments into React nodes (text is always escaped by React).
//
// The rules follow the server's parsers (`services/mentions.py`,
// `services/hashtags.py`), and only what the server resolved is linked:
//   • `@name` links to /@handle only when the server lists that handle in the
//     post's `mentions`. Unknown names, e-mails and look-alikes stay text.
//   • `#tag` links to /tag/<tag> when it is in the post's `tags` (or, for text
//     with no tag list such as a bio or the composer preview, when it parses).
//   • http(s) URLs link out. A `#` or `@` inside a URL is part of the URL.

export interface MentionRef {
  handle: string;
  did: string;
}

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "mention"; text: string; href: string; handle: string; did: string }
  | { kind: "tag"; text: string; href: string; tag: string }
  | { kind: "url"; text: string; href: string };

export interface LinkifyOptions {
  /** Server-resolved mentions. Missing → no @name is linked. */
  mentions?: readonly MentionRef[] | null;
  /** The post's stored tags. Missing → any parsed #tag is linked. */
  tags?: readonly string[] | null;
}

// A word character in any script, or a combining mark: a name or tag must
// not touch one on either side (so `a@b`, `#cafè`, Cyrillic look-alikes and
// over-long names are plain text, never cut short).
const W = String.raw`\p{L}\p{N}\p{M}_`;

const TOKEN_RE = new RegExp(
  String.raw`(https?:\/\/[^\s<>"]+)` +                              // 1: URL
  String.raw`|(www\.[^\s<>"]+)` +                                   // 2: bare www. (text)
  String.raw`|(?<![${W}@\/])@([A-Za-z0-9_]{1,30})(?![${W}])` +     // 3: @name
  String.raw`|(?<![${W}#&\/])#([A-Za-z0-9_]{1,50})(?![${W}])`,     // 4: #tag
  "gu",
);

const TRAILING_PUNCT = ".,;:!?)]}'";

export function linkify(content: string, opts: LinkifyOptions = {}): Segment[] {
  if (!content) return [];
  const byHandle = new Map<string, MentionRef>();
  for (const m of opts.mentions ?? []) {
    if (m?.handle) byHandle.set(m.handle.toLowerCase(), m);
  }
  const tagSet = opts.tags ? new Set(opts.tags.map((t) => t.toLowerCase().replace(/^#/, ""))) : null;

  const out: Segment[] = [];
  const pushText = (text: string) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last && last.kind === "text") last.text += text;
    else out.push({ kind: "text", text });
  };

  let last = 0;
  TOKEN_RE.lastIndex = 0;
  for (let m = TOKEN_RE.exec(content); m !== null; m = TOKEN_RE.exec(content)) {
    const [matched, url, www, name, tag] = m;
    pushText(content.slice(last, m.index));
    last = m.index + matched.length;

    if (url) {
      let href = url;
      let trailing = "";
      while (href.length > 0 && TRAILING_PUNCT.includes(href[href.length - 1])) {
        trailing = href[href.length - 1] + trailing;
        href = href.slice(0, -1);
      }
      if (/^https?:\/\/[^/?#]/i.test(href)) out.push({ kind: "url", text: href, href });
      else pushText(href);
      pushText(trailing);
    } else if (www) {
      pushText(www);
    } else if (name) {
      const ref = byHandle.get(name.toLowerCase());
      if (ref) {
        out.push({
          kind: "mention",
          text: matched,
          handle: ref.handle,
          did: ref.did,
          href: `/@${encodeURIComponent(ref.handle)}`,
        });
      } else {
        pushText(matched);
      }
    } else if (tag) {
      const lower = tag.toLowerCase();
      const isTag = !/^\d+$/.test(tag) && (tagSet === null || tagSet.has(lower));
      if (isTag) out.push({ kind: "tag", text: matched, tag: lower, href: `/tag/${encodeURIComponent(lower)}` });
      else pushText(matched);
    }
  }
  pushText(content.slice(last));
  return out;
}
