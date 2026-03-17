export function ActivityCard({ item }: { item: Record<string, unknown> }) {
  const isPost = item.item_type === "post";

  return (
    <div className="flex items-start gap-3 py-3 border-b border-slate-100 dark:border-slate-800 last:border-0">
      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-base">
          {isPost ? "post_add" : "bolt"}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">
          {(item.stream_type as string) ?? (item.item_type as string)}
        </p>
        <p className="text-xs text-slate-500 line-clamp-1 mt-0.5">
          {item.content as string}
        </p>
      </div>
      <span className="text-xs text-slate-400 whitespace-nowrap">
        {isPost ? "post" : "event"}
      </span>
    </div>
  );
}
