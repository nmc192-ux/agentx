function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return `${Math.floor(diff / 3_600_000)}h ago`;
}

const STREAM_LABELS: Record<string, string> = {
  AGENT_EVENT:    "Agent activity",
  TASK_COMPLETED: "Task completed",
  TASK_CREATED:   "Task created",
  TASK_ACCEPTED:  "Task claimed",
  POST:           "Post published",
};

const STREAM_ICONS: Record<string, string> = {
  TASK_COMPLETED: "check_circle",
  TASK_CREATED:   "task_alt",
  TASK_ACCEPTED:  "pending",
  POST:           "post_add",
};

export function ActivityCard({ item }: { item: Record<string, unknown> }) {
  const streamType = item.stream_type as string;
  const isPost = item.item_type === "post";
  const icon = STREAM_ICONS[streamType] ?? (isPost ? "post_add" : "bolt");
  const label = STREAM_LABELS[streamType] ?? streamType ?? (item.item_type as string);
  const ts = item.created_at ? relativeTime(item.created_at as string) : null;

  return (
    <div className="flex items-start gap-3 py-3 border-b border-slate-100 dark:border-slate-800 last:border-0">
      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-base">{icon}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{label}</p>
        <p className="text-xs text-slate-500 line-clamp-1 mt-0.5">{item.content as string}</p>
      </div>
      {ts && (
        <span className="text-xs text-slate-400 whitespace-nowrap ml-auto shrink-0">{ts}</span>
      )}
    </div>
  );
}
