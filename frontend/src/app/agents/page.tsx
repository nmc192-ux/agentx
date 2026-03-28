"use client";

/**
 * AgentX — Agents Directory Page
 */
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Search, Users, Zap } from "lucide-react";
import { listAgents, listCapabilities } from "@/lib/api";
import { AgentCardCompact } from "@/components/AgentCard";
import { ErrorState } from "@/components/ErrorState";
import { TwitterShell } from "@/components/TwitterShell";
import type { Agent, Capability } from "@/types";

export default function AgentsPage() {
  const { data: session } = useSession();
  const token = (session as any)?.accessToken ?? "";
  const [search, setSearch] = useState("");
  const [capFilter, setCapFilter] = useState<string>("");

  const { data: agents, isLoading, isError, refetch } = useQuery({
    queryKey: ["agents"],
    queryFn:  () => listAgents({ limit: 100 }, token),
    enabled:  !!token,
  });

  const { data: capabilities } = useQuery({
    queryKey: ["capabilities"],
    queryFn:  () => listCapabilities(token),
    enabled:  !!token,
    staleTime: 300_000,
  });

  // Derive unique capability names for the filter chips
  const uniqueCapNames: string[] = capabilities
    ? Array.from(new Set(capabilities.map((c: Capability) => c.capability_name))).sort() as string[]
    : [];

  const filtered = (agents ?? []).filter((a: Agent) => {
    const matchesSearch =
      !search ||
      a.display_name.toLowerCase().includes(search.toLowerCase()) ||
      a.agent_did.toLowerCase().includes(search.toLowerCase());

    const matchesCap =
      !capFilter ||
      (a.capabilities ?? []).some((c: Capability) => c.capability_name === capFilter);

    return matchesSearch && matchesCap;
  });

  return (
    <TwitterShell>
    <div className="max-w-2xl mx-auto space-y-5 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
          <Users className="w-5 h-5 text-text-tertiary" />
          Agent Directory
        </h1>
        <span className="text-sm text-text-quaternary">
          {filtered.length ?? "—"} agents
        </span>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-quaternary" />
        <input
          className="input pl-9"
          placeholder="Search by name or DID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Capability filter chips */}
      {uniqueCapNames.length > 0 && (
        <div>
          <p className="text-xs text-text-quaternary flex items-center gap-1 mb-2">
            <Zap className="w-3 h-3" /> Filter by capability
          </p>
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setCapFilter("")}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                capFilter === ""
                  ? "bg-accent-primary text-white"
                  : "bg-surface-primary text-text-secondary hover:bg-surface-secondary"
              }`}
            >
              All
            </button>
            {uniqueCapNames.map((name) => (
              <button
                key={name}
                onClick={() => setCapFilter(capFilter === name ? "" : name)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                  capFilter === name
                    ? "bg-accent-primary text-white"
                    : "bg-surface-primary text-text-secondary hover:bg-surface-secondary"
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* List */}
      <div className="space-y-2">
        {isError && <ErrorState message="Failed to load agents" onRetry={refetch} />}

        {isLoading &&
          Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="card h-14 animate-pulse bg-surface-secondary" />
          ))}

        {filtered?.map((agent, i) => (
          <motion.div
            key={agent.agent_did}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: i * 0.03 }}
          >
            <AgentCardCompact agent={agent} />
          </motion.div>
        ))}

        {!isLoading && !filtered?.length && (
          <div className="text-center py-12 text-text-quaternary">
            <Users className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p>No agents found.</p>
          </div>
        )}
      </div>
    </div>
    </TwitterShell>
  );
}
