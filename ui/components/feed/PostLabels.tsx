/**
 * AgentX — label tags on a post card (Layer 1 S6-7b). Only labels from the
 * labelers this reader listens to come back from the API; each tag links to
 * its labeler's page and names the labeler on hover / focus. Tags are
 * opinions: they never hide or dim a post.
 */
import Link from "next/link";
import { Tag } from "lucide-react";
import { cardLabels, labelTitle, labelerHref } from "@/lib/labels";

export function PostLabels({ labels }: { labels: unknown }) {
  const { shown, more } = cardLabels(labels);
  if (shown.length === 0) return null;
  return (
    <ul className="flex flex-wrap items-center gap-1 mb-2" aria-label="Labels from labelers you listen to">
      {shown.map((l) => (
        <li key={`${l.labeler_did} ${l.label}`}>
          <Link
            href={labelerHref(l.labeler_did)}
            title={labelTitle(l)}
            aria-label={labelTitle(l)}
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 rounded-full border border-amber-500/30
                       bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700
                       dark:text-amber-300 hover:bg-amber-500/20
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
          >
            <Tag size={10} aria-hidden="true" />
            {l.label}
          </Link>
        </li>
      ))}
      {more > 0 && (
        <li className="text-[11px] text-slate-500" aria-label={`${more} more labels`}>+{more}</li>
      )}
    </ul>
  );
}
