function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return `${Math.floor(diff / 3_600_000)}h ago`;
}

const TYPE_MAP: Record<string, { icon: string; color: string; label: string }> = {
  TASK_CREATED:   { icon: "task_alt",     color: "text-blue-500",  label: "Task created"   },
  TASK_ACCEPTED:  { icon: "pending",      color: "text-amber-500", label: "Task claimed"   },
  TASK_COMPLETED: { icon: "check_circle", color: "text-green-500", label: "Task completed" },
  NEW_POST:       { icon: "post_add",     color: "text-slate-400", label: "Post published" },
};

export function TaskCard({ item }: { item: Record<string, unknown> }) {
  const streamType = (item.stream_type as string) ?? "";
  const meta = TYPE_MAP[streamType] ?? { icon: "bolt", color: "text-slate-400", label: streamType || "Event" };
  const content = (item.content as string) ?? "";
  const ts = item.created_at ? relativeTime(item.created_at as string) : null;

  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
      <span className={`material-symbols-outlined text-base mt-0.5 flex-shrink-0 ${meta.color}`}>
        {meta.icon}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{meta.label}</p>
        <p className="text-xs text-slate-500 line-clamp-2 mt-0.5">{content.slice(0, 120)}</p>
      </div>
      {ts && (
        <span className="text-xs text-slate-400 whitespace-nowrap flex-shrink-0">{ts}</span>
      )}
    </div>
  );
}
