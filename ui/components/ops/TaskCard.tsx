function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return `${Math.floor(diff / 3_600_000)}h ago`;
}

const TYPE_MAP: Record<string, { icon: string; color: string; label: string }> = {
  // Activity stream event types
  TASK_CREATED:   { icon: "task_alt",     color: "text-blue-500",   label: "Task created"   },
  TASK_ACCEPTED:  { icon: "pending",      color: "text-amber-500",  label: "Task claimed"   },
  TASK_COMPLETED: { icon: "check_circle", color: "text-green-500",  label: "Task completed" },
  NEW_POST:       { icon: "post_add",     color: "text-slate-400",  label: "Post published" },
  AGENT_EVENT:    { icon: "smart_toy",    color: "text-purple-500", label: "Agent activity" },
  TRUST_UPDATE:   { icon: "verified",     color: "text-teal-500",   label: "Trust updated"  },
  // Post post_type values from the unified feed query
  TASK:           { icon: "task_alt",     color: "text-blue-500",   label: "Task posted"    },
  UPDATE:         { icon: "update",       color: "text-green-500",  label: "Agent response" },
  OFFER:          { icon: "handshake",    color: "text-amber-500",  label: "Offer"          },
  REQUEST:        { icon: "help_outline", color: "text-orange-500", label: "Request"        },
  PROPOSAL:       { icon: "lightbulb",    color: "text-indigo-500", label: "Proposal"       },
  ACHIEVEMENT:    { icon: "emoji_events", color: "text-yellow-500", label: "Achievement"    },
  MILESTONE:      { icon: "flag",         color: "text-rose-500",   label: "Milestone"      },
};

export function TaskCard({ item }: { item: Record<string, unknown> }) {
  const streamType = (item.stream_type as string) ?? "";
  const meta = TYPE_MAP[streamType] ?? { icon: "bolt", color: "text-slate-400", label: streamType || "Event" };
  const title   = (item.title   as string) ?? "";
  const content = (item.content as string) ?? "";
  const body    = title || content;                       // prefer title; fall back to content
  const detail  = title ? content : "";                  // show content as sub-line only when title exists
  const ts = item.created_at ? relativeTime(item.created_at as string) : null;

  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
      <span className={`material-symbols-outlined text-base mt-0.5 flex-shrink-0 ${meta.color}`}>
        {meta.icon}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{meta.label}</p>
          {ts && <span className="text-xs text-slate-400 ml-auto whitespace-nowrap flex-shrink-0">{ts}</span>}
        </div>
        <p className="text-xs text-slate-700 dark:text-slate-200 font-medium mt-0.5 line-clamp-1">{body.slice(0, 100)}</p>
        {detail && <p className="text-xs text-slate-500 line-clamp-1 mt-0.5">{detail.slice(0, 100)}</p>}
      </div>
    </div>
  );
}
