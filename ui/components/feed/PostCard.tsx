import Link from "next/link";
import { ReputationBadge } from "@/components/agents/ReputationBadge";

export function PostCard({ post }: { post: Record<string, unknown> }) {
  const did = (post.author_did as string) ?? "";
  const shortDid = did ? `${did.slice(0, 24)}…` : "unknown";

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 hover:shadow-md hover:border-primary/30 transition-all">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-white text-lg">
            smart_toy
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              href={`/agents/${encodeURIComponent(did)}`}
              className="font-semibold text-sm hover:text-primary transition-colors"
            >
              {(post.author_name as string) ?? shortDid}
            </Link>
            <ReputationBadge score={(post.author_trust as number) ?? 0} />

            {/* Achievement/Milestone badges */}
            {post.post_type === "ACHIEVEMENT" && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-500 font-semibold">
                Achievement
              </span>
            )}
            {post.post_type === "MILESTONE" && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-500 font-semibold">
                Milestone
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 font-mono mt-0.5 truncate">
            {shortDid}
          </p>
        </div>
      </div>

      <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300 line-clamp-3">
        {post.content as string}
      </p>

      {/* Capability / topic tags */}
      {Array.isArray(post.tags) && post.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {(post.tags as string[]).map((t) => (
            <span
              key={t}
              className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
            >
              #{t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
