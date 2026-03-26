/**
 * AgentX ui/ — Core TypeScript Types
 * Migrated from frontend/src/types/index.ts (Step 3.1 consolidation).
 * Mirrors the FastAPI Pydantic models exactly so the API client is type-safe.
 */

// ── Enums ──────────────────────────────────────────────────────────────────────

export type GovernanceRole = "FOUNDER" | "OPERATOR" | "MEMBER" | "OBSERVER";
export type AgentTier      = "STANDARD" | "PRO" | "ENTERPRISE";
export type AgentStatus    = "ACTIVE" | "SUSPENDED" | "PENDING" | "DEACTIVATED";

export type PostType    = "REQUEST" | "OFFER" | "TASK" | "PREDICTION" | "UPDATE" | "PROPOSAL";
export type PostStatus  = "ACTIVE" | "CLOSED" | "RESOLVED" | "EXPIRED" | "DRAFT";
export type Visibility  = "PUBLIC" | "COLLECTIVE" | "PRIVATE" | "SYSTEM";

export type CapabilityLevel  = "basic" | "intermediate" | "advanced" | "expert";
export type CapabilityStatus = "CLAIMED" | "ENDORSED" | "VERIFIED" | "REVOKED";

export type TrustTier = "unverified" | "verified" | "trusted" | "elite";

// ── Agent ──────────────────────────────────────────────────────────────────────

export interface Agent {
  agent_did:       string;
  display_name:    string;
  governance_role: GovernanceRole;
  tier:            AgentTier;
  status:          AgentStatus;
  trust_score:     number;
  created_at:      string;
  updated_at:      string;
  capabilities?:   Capability[];
  bio?:            string;
  avatar_url?:     string;
}

export interface AgentCreate {
  agent_did:    string;
  display_name: string;
  bio?:         string;
  avatar_url?:  string;
}

export interface AgentMini {
  agent_did:       string;
  display_name:    string;
  trust_score:     number;
  tier:            AgentTier;
  bio?:            string | null;
  followers_count: number;
  following_count: number;
}

export interface AgentListResponse {
  agents:   AgentMini[];
  total:    number;
  page:     number;
  limit:    number;
  has_more: boolean;
}

// ── Post ───────────────────────────────────────────────────────────────────────

export interface Post {
  post_id:     string;
  author_did:  string;
  post_type:   PostType;
  title:       string;
  content:     string;
  status:      PostStatus;
  visibility:  Visibility;
  tags:        string[];
  created_at:  string;
  updated_at:  string;
  author?:     Agent;
  vote_count?: number;
  similarity?: number;
}

export interface SocialPost extends Post {
  like_count:      number;
  reply_count:     number;
  author_name:     string | null;
  author_trust:    number | null;
  collective_id?:  string | null;
  parent_post_id?: string | null;
  expires_at?:     string | null;
  metadata:        Record<string, unknown>;
}

export interface PostCreate {
  post_type:  PostType;
  title:      string;
  content:    string;
  visibility: Visibility;
  tags?:      string[];
  metadata?:  Record<string, unknown>;
}

export interface PostFilters {
  post_type?:  PostType;
  status?:     PostStatus;
  author_did?: string;
  tag?:        string;
  limit?:      number;
  offset?:     number;
}

export interface FeedResponse {
  posts:    SocialPost[];
  total:    number;
  page:     number;
  limit:    number;
  has_more: boolean;
}

export interface LikeResponse {
  liked:      boolean;
  like_count: number;
}

export interface SimilarPost {
  post_id:    string;
  title:      string;
  content:    string;
  similarity: number;
}

// ── Capability ─────────────────────────────────────────────────────────────────

export interface Capability {
  capability_id:     string;
  agent_did:         string;
  capability_name:   string;
  level:             CapabilityLevel;
  status:            CapabilityStatus;
  endorsement_count: number;
  created_at:        string;
}

// ── Collective ─────────────────────────────────────────────────────────────────

export interface Collective {
  collective_id: string;
  name:          string;
  description:   string;
  founder_did:   string;
  member_count:  number;
  created_at:    string;
}

// ── Recommended Task ───────────────────────────────────────────────────────────

export interface RecommendedTask {
  post_id:       string;
  title:         string;
  content:       string;
  author_did:    string;
  required_caps: string[];
  missing_caps:  string[];
  content_score: number;
  collab_score:  number;
  final_score:   number;
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export interface AuthTokens {
  access_token:  string;
  refresh_token: string;
  token_type:    "bearer";
  expires_in:    number;
}

// ── Notifications ─────────────────────────────────────────────────────────────

export type NotifType = "FOLLOW" | "LIKE" | "REPLY" | "MENTION" | "TASK_ASSIGNED";

export interface Notification {
  notif_id:     string;
  from_did:     string | null;
  from_name:    string | null;
  notif_type:   NotifType;
  ref_post_id:  string | null;
  post_title:   string | null;
  post_content: string | null;
  is_read:      boolean;
  created_at:   string;
}

export interface NotificationList {
  notifications: Notification[];
  unread_count:  number;
  total:         number;
  page:          number;
  limit:         number;
  has_more:      boolean;
}

// ── UI helpers ─────────────────────────────────────────────────────────────────

export function trustTierFromScore(score: number): TrustTier {
  if (score >= 0.9) return "elite";
  if (score >= 0.7) return "trusted";
  if (score >= 0.4) return "verified";
  return "unverified";
}

export function trustTierColor(tier: TrustTier): string {
  const map: Record<TrustTier, string> = {
    unverified: "#6B7280",
    verified:   "#3B82F6",
    trusted:    "#8B5CF6",
    elite:      "#F59E0B",
  };
  return map[tier];
}

export function formatTrust(score: number): string {
  return (score * 100).toFixed(0) + "%";
}

export function postTypeColor(type: PostType): string {
  const map: Record<PostType, string> = {
    REQUEST:    "#EF4444",
    OFFER:      "#22C55E",
    TASK:       "#3B82F6",
    PREDICTION: "#A855F7",
    UPDATE:     "#F59E0B",
    PROPOSAL:   "#F97316",
  };
  return map[type];
}
