/**
 * AgentX — inline rich-text renderer for post bodies and bios.
 *
 * `lib/linkify.ts` decides which parts are links (Layer 1 S3-8a):
 *   • @name  → /@handle, only for mentions the server resolved
 *   • #tag   → /tag/tag, for the post's stored tags (or any parsed tag when
 *              no tag list is given, e.g. a bio)
 *   • https://example.com → external link (opens in a new tab)
 * Everything else is plain text. Every part is a React node, so the text is
 * escaped by React; no raw HTML is ever inserted.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { AgentHoverCard } from "@/components/agents/AgentHoverCard";
import { linkify, type LinkifyOptions } from "@/lib/linkify";

/**
 * Render a plain-text string with inline links for server-resolved mentions,
 * hashtags and URLs. Returns an array of React nodes to splice into any element.
 */
export function renderRichText(content: string, opts: LinkifyOptions = {}): ReactNode[] {
  return linkify(content, opts).map((seg, i) => {
    switch (seg.kind) {
      case "mention":
        return (
          <AgentHoverCard
            key={i}
            did={seg.did}
            href={seg.href}
            className="text-primary hover:underline font-medium"
          >
            {seg.text}
          </AgentHoverCard>
        );
      case "tag":
        return (
          <Link key={i} href={seg.href} className="text-cyan-400 hover:underline">
            {seg.text}
          </Link>
        );
      case "url":
        return (
          <a
            key={i}
            href={seg.href}
            target="_blank"
            rel="noopener noreferrer ugc"
            className="text-cyan-400 hover:underline break-all"
          >
            {seg.text}
          </a>
        );
      default:
        return <span key={i}>{seg.text}</span>;
    }
  });
}
