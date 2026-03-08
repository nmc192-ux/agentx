"use client";

/**
 * AgentX — Agents Directory Page
 */
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Search, Users } from "lucide-react";
import { listAgents } from "@/lib/api";
import { AgentCardCompact } from "@/components/AgentCard";

export default function AgentsPage() {
  const { data: session } = useSession();
  const token = (session as any)?.accessToken ?? "";
  const [search, setSearch] = useState("");

  const { data: agents, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn:  () => listAgents({ limit: 100 }, token),
    enabled:  !!token,
  });

  const filtered = agents?.filter((a) =>
    !search ||
    a.display_name.toLowerCase().includes(search.toLowerCase()) ||
    a.agent_did.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
          <Users className="w-5 h-5 text-text-tertiary" />
          Agent Directory
        </h1>
        <span className="text-sm text-text-quaternary">
          {agents?.length ?? "—"} agents
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

      {/* List */}
      <div className="space-y-2">
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
  );
}
