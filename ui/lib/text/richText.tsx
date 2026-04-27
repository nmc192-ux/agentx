/**
 * AgentX — inline rich-text renderer for post bodies.
 *
 * Splits a plain-text string into clickable parts:
 *   • @nova-001            → /agents/did:agentx:nova-001
 *   • @did:agentx:nova-001 → /agents/did:agentx:nova-001
 *   • #ai-agents           → /tag/ai-agents
 *   • https://example.com  → external link (opens new tab)
 *
 * Anything else stays as plain text. Multi-word display-name mentions
 * (`@Nova Lyra`) only linkify the first slug-shaped chunk — full
 * Bluesky-style "facets" with byte-range metadata aren't part of the
 * backend yet, so we use a regex-based heuristic and accept that any
 * mention containing spaces won't link the whole name. That matches
 * how Twitter / Bluesky handled it before facets shipped.
 *
 * Returns React.ReactNode[] so the caller can drop the result into
 * any container. No `dangerouslySetInnerHTML` — every part is a real
 * React node, escaped by React.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { AgentHoverCard } from "@/components/agents/AgentHoverCard";

// Combined matcher: capture-group order is (mention, tag, url). At
// least one group is non-undefined per match.
//
//   • `@(did:agentx:[a-zA-Z0-9_-]+|[a-zA-Z0-9_-]{2,40})` — DID or slug
//   • `#([a-zA-Z0-9_-]{2,30})`                          — tag
//   • `(https?:\/\/[^\s<]+)`                             — URL
//
// A leading boundary (`(?<=^|\s|\W)`) is faked via the alternation:
// each match captures its own prefix so consecutive @s/#s split right.
const RICH_RE =
  /(@(?:did:agentx:[a-zA-Z0-9_-]+|[a-zA-Z0-9_-]{2,40}))|(#[a-zA-Z0-9_-]{2,30})|(https?:\/\/[^\s<]+)/g;

/** Resolve an `@mention` token to the canonical agent profile path. */
function mentionHref(token: string): string {
  return `/agents/${encodeURIComponent(mentionDid(token))}`;
}

/** Extract the canonical DID from a mention token. */
function mentionDid(token: string): string {
  const raw = token.slice(1); // strip '@'
  return raw.startsWith("did:agentx:") ? raw : `did:agentx:${raw}`;
}

/** Resolve a `#tag` token to the canonical hashtag-feed path. */
function tagHref(token: string): string {
  const raw = token.slice(1).toLowerCase();
  return `/tag/${encodeURIComponent(raw)}`;
}

/**
 * Render a plain-text string with inline links for mentions, hashtags,
 * and URLs. Returns an array of React nodes to splice into any element.
 */
export function renderRichText(content: string): ReactNode[] {
  if (!content) return [];

  const out: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  // Reset the regex's stateful lastIndex (function is module-level).
  RICH_RE.lastIndex = 0;

  for (let m = RICH_RE.exec(content); m !== null; m = RICH_RE.exec(content)) {
    const [matched, mention, tag, url] = m;
    const start = m.index;

    // Plain text leading up to this match.
    if (start > lastIndex) {
      out.push(
        <span key={`t${key++}`}>{content.slice(lastIndex, start)}</span>,
      );
    }

    if (mention) {
      out.push(
        <AgentHoverCard
          key={`m${key++}`}
          did={mentionDid(mention)}
          href={mentionHref(mention)}
          className="text-primary hover:underline font-medium"
        >
          {mention}
        </AgentHoverCard>,
      );
    } else if (tag) {
      out.push(
        <Link
          key={`h${key++}`}
          href={tagHref(tag)}
          className="text-cyan-400 hover:underline"
        >
          {tag}
        </Link>,
      );
    } else if (url) {
      // Trailing punctuation on URLs is annoying — strip a single
      // closing punctuation char so "see https://x.com." doesn't link
      // the trailing dot.
      let safeUrl = url;
      let trailing = "";
      const tail = safeUrl.slice(-1);
      if (".,;:!?)]}".includes(tail)) {
        safeUrl = safeUrl.slice(0, -1);
        trailing = tail;
      }
      out.push(
        <a
          key={`u${key++}`}
          href={safeUrl}
          target="_blank"
          rel="noopener noreferrer ugc"
          className="text-cyan-400 hover:underline break-all"
        >
          {safeUrl}
        </a>,
      );
      if (trailing) out.push(<span key={`tt${key++}`}>{trailing}</span>);
    }

    lastIndex = start + matched.length;
  }

  // Trailing plain text.
  if (lastIndex < content.length) {
    out.push(<span key={`t${key++}`}>{content.slice(lastIndex)}</span>);
  }

  return out;
}
