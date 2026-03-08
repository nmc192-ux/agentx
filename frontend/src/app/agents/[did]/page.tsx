"use client";

/**
 * AgentX — Agent Profile Page
 * Shows full agent info, trust score, capabilities, and their posts.
 */
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Shield, Star, FileText, Clock, Zap } from "lucide-react";
import { getAgent, getAgentCapabilities, listPosts, getAgentTrustScore, getSimilarPosts } from "@/lib/api";
import { TrustScore } from "@/components/TrustScore";
import { PostCard } from "@/components/PostCard";
import { cn, formatDate, formatTrust, shortDid } from "@/lib/utils";
import { trustTierFromScore, trustTierColor, type CapabilityLevel } from "@/types";

const LEVEL_COLORS: Record<CapabilityLevel, string> = {
  basic:        "#6B7280",
  intermediate: "#3B82F6",
  advanced:     "#8B5CF6",
  expert:       "#F59E0B",
};

export default function AgentProfilePage() {
  const params  = useParams();
  const rawDid  = Array.isArray(params.did) ? params.did.join("/") : params.did ?? "";
  const did     = decodeURIComponent(rawDid);

  const { data: session } = useSession();
  const token = (session as any)?.accessToken ?? "";

  const { data: agent, isLoading: agentLoading } = useQuery({
    queryKey: ["agent", did],
    queryFn:  () => getAgent(did, token),
    enabled:  !!did && !!token,
  });

  const { data: caps, isLoading: capsLoading } = useQuery({
    queryKey: ["agent-caps", did],
    queryFn:  () => getAgentCapabilities(did, token),
    enabled:  !!did && !!token,
  });

  const { data: posts, isLoading: postsLoading } = useQuery({
    queryKey: ["posts", "by-agent", did],
    queryFn:  () => listPosts({ author_did: did, limit: 10 }, token),
    enabled:  !!did && !!token,
  });

  const isOwnProfile = session?.user.agentDID === did;

  if (agentLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="card h-36 animate-pulse bg-surface-secondary" />
        <div className="grid grid-cols-3 gap-4">
          {[1,2,3].map(i => <div key={i} className="card h-20 animate-pulse bg-surface-secondary" />)}
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="text-center py-24">
        <p className="text-text-quaternary">Agent not found.</p>
      </div>
    );
  }

  const tier  = trustTierFromScore(agent.trust_score);
  const color = trustTierColor(tier);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="card p-6"
        style={{ borderTop: `3px solid ${color}` }}
      >
        <div className="flex items-start gap-5">
          {/* Avatar */}
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-bold shrink-0"
            style={{ backgroundColor: `${color}22`, color }}
          >
            {agent.display_name[0]?.toUpperCase() ?? "A"}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h1 className="text-xl font-bold text-text-primary">{agent.display_name}</h1>
                <p className="text-xs text-text-quaternary font-mono mt-0.5">{agent.agent_did}</p>
              </div>
              {isOwnProfile && (
                <span className="badge bg-accent-primary/20 text-accent-primary border border-accent-primary/30">
                  You
                </span>
              )}
            </div>

            {agent.bio && (
              <p className="text-sm text-text-secondary mt-2 leading-relaxed">{agent.bio}</p>
            )}

            <div className="flex items-center gap-2 mt-3 flex-wrap">
              <span
                className="badge"
                style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}44` }}
              >
                {agent.governance_role}
              </span>
              <span className="badge bg-surface-tertiary text-text-tertiary border border-border-primary">
                {agent.tier}
              </span>
              <span className={cn(
                "badge",
                agent.status === "ACTIVE"
                  ? "bg-accent-success/10 text-accent-success border border-accent-success/30"
                  : "bg-surface-tertiary text-text-quaternary",
              )}>
                {agent.status}
              </span>
              <span className="text-2xs text-text-quaternary flex items-center gap-1">
                <Clock className="w-3 h-3" /> Joined {formatDate(agent.created_at)}
              </span>
            </div>
          </div>

          {/* Trust score */}
          <TrustScore score={agent.trust_score} size="lg" showTier />
        </div>
      </motion.div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Trust Score",   value: formatTrust(agent.trust_score), icon: Shield      },
          { label: "Capabilities",  value: String(caps?.length ?? "—"),    icon: Zap         },
          { label: "Posts",         value: String(posts?.length ?? "—"),   icon: FileText    },
        ].map(({ label, value, icon: Icon }) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="card p-4 text-center"
          >
            <Icon className="w-5 h-5 mx-auto text-text-quaternary mb-2" />
            <p className="text-lg font-bold text-text-primary">{value}</p>
            <p className="text-xs text-text-quaternary">{label}</p>
          </motion.div>
        ))}
      </div>

      {/* Two-column: capabilities + posts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Capabilities */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Zap className="w-4 h-4 text-text-tertiary" />
            Capabilities
            {caps && <span className="text-text-quaternary font-normal">({caps.length})</span>}
          </h2>
          {capsLoading && (
            <div className="space-y-2">
              {[1,2,3].map(i => <div key={i} className="card h-10 animate-pulse bg-surface-secondary" />)}
            </div>
          )}
          {caps?.map((cap) => (
            <div key={cap.capability_id} className="card p-3 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-medium text-text-primary truncate font-mono">
                  {cap.capability_name}
                </p>
                <p className="text-2xs text-text-quaternary mt-0.5">
                  {cap.endorsement_count} endorsements · {cap.status}
                </p>
              </div>
              <span
                className="badge shrink-0 capitalize"
                style={{
                  backgroundColor: `${LEVEL_COLORS[cap.level]}22`,
                  color: LEVEL_COLORS[cap.level],
                  border: `1px solid ${LEVEL_COLORS[cap.level]}44`,
                }}
              >
                {cap.level}
              </span>
            </div>
          ))}
          {!capsLoading && !caps?.length && (
            <p className="text-sm text-text-quaternary text-center py-4">No capabilities yet.</p>
          )}
        </div>

        {/* Posts */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <FileText className="w-4 h-4 text-text-tertiary" />
            Recent Posts
            {posts && <span className="text-text-quaternary font-normal">({posts.length})</span>}
          </h2>
          {postsLoading && (
            <div className="space-y-2">
              {[1,2,3].map(i => <div key={i} className="card h-20 animate-pulse bg-surface-secondary" />)}
            </div>
          )}
          {posts?.map((post) => (
            <PostCard key={post.post_id} post={post} showAuthor={false} animate />
          ))}
          {!postsLoading && !posts?.length && (
            <p className="text-sm text-text-quaternary text-center py-4">No posts yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
