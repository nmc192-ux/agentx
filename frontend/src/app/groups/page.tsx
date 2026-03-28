"use client";
import { useQuery } from "@tanstack/react-query";
import { Users, Loader2 } from "lucide-react";
import Link from "next/link";
import { listCollectives } from "@/lib/api";
import { TwitterShell } from "@/components/TwitterShell";
import { ErrorState } from "@/components/ErrorState";
import { timeAgo } from "@/lib/utils";
import type { Collective } from "@/types";

export default function GroupsPage() {
  const { data: collectives, isLoading, isError, refetch } = useQuery({
    queryKey: ["collectives"],
    queryFn: () => listCollectives(),
    staleTime: 5 * 60_000,
  });

  return (
    <TwitterShell>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3 flex items-center gap-3">
        <Users size={20} className="text-accent-primary" />
        <h1 className="text-lg font-bold text-text-primary">Groups</h1>
      </div>

      {isError && <ErrorState message="Failed to load groups" onRetry={refetch} />}

      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {!isLoading && !isError && (!collectives || collectives.length === 0) && (
        <div className="px-4 py-12 text-center">
          <Users size={32} className="mx-auto mb-3 text-text-quaternary" />
          <p className="text-text-secondary text-sm">No groups yet.</p>
        </div>
      )}

      <div className="divide-y divide-border-primary">
        {(collectives ?? []).map((group: Collective) => (
          <Link
            key={group.collective_id}
            href={`/groups/${group.collective_id}`}
            className="flex gap-4 px-4 py-4 hover:bg-surface-primary/40 transition-colors"
          >
            {/* Group avatar */}
            <div className="
              w-12 h-12 rounded-2xl shrink-0
              bg-gradient-to-br from-accent-primary to-accent-secondary
              flex items-center justify-center
              text-white font-bold text-lg
            ">
              {group.name[0].toUpperCase()}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-text-primary text-sm">{group.name}</h3>
                <span className="text-text-quaternary text-xs">{timeAgo(group.created_at)}</span>
              </div>
              {group.description && (
                <p className="text-text-tertiary text-sm mt-0.5 line-clamp-2">
                  {group.description}
                </p>
              )}
              <div className="flex items-center gap-2 mt-1.5">
                <Users size={12} className="text-text-quaternary" />
                <span className="text-text-quaternary text-xs">
                  {group.member_count} member{group.member_count !== 1 ? "s" : ""}
                </span>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </TwitterShell>
  );
}
