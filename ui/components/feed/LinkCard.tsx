"use client";

/**
 * AgentX — the link card under a post (Layer 1 S4-10b): image, title,
 * description and site for the post's first link. The server fetched it
 * and re-hosted the image, so nothing here loads from the linked site.
 * What it shows is decided in lib/linkCard.ts.
 */
/* eslint-disable @next/next/no-img-element -- the thumbnail is the API's own
   /media/ file with its own cache headers; next/image would proxy it. */
import { ExternalLink } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { CARD_REL, linkCardView } from "@/lib/linkCard";
import { mediaSrc } from "@/lib/postMedia";
import type { LinkCard as LinkCardData } from "@/types";

const imageSrc = (url: unknown) => mediaSrc(typeof url === "string" ? url : null, API_BASE);

export function LinkCard({ card }: { card: LinkCardData | null | undefined }) {
  const view = linkCardView(card, imageSrc);
  if (!view) return null;
  return (
    <a
      data-link-card
      href={view.href}
      target="_blank"
      rel={CARD_REL}
      referrerPolicy="no-referrer"
      onClick={(e) => e.stopPropagation()}
      className="mt-2 mb-3 block overflow-hidden rounded-xl border border-slate-700/70
                 bg-slate-900/40 hover:bg-slate-800/50 transition-colors
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
      aria-label={`${view.title} (${view.host}, opens in a new tab)`}
    >
      {view.imageSrc && (
        <img
          src={view.imageSrc}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="w-full max-h-64 object-cover bg-slate-800"
        />
      )}
      <div className="px-3 py-2 space-y-0.5">
        <p className="flex items-center gap-1 text-[11px] text-slate-500">
          <ExternalLink className="w-3 h-3" aria-hidden="true" />
          {view.site}
        </p>
        <p className="text-sm font-medium text-slate-100 line-clamp-2">{view.title}</p>
        {view.description && (
          <p className="text-xs text-slate-400 line-clamp-2">{view.description}</p>
        )}
      </div>
    </a>
  );
}
