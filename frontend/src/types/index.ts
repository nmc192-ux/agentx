/**
 * AgentX Frontend — Core TypeScript Types
 * Mirrors the FastAPI Pydantic models exactly so the API client is type-safe.
 *
 * SOURCE: workspace/shared/agentx_api_v1.yaml
 */

// ── Enums ──────────────────────────────────────────────────────────────────────

export type GovernanceRole = "FOUNDER" | "OPERATOR" | "MEMBER" | "OBSERVER";
export type AgentTier      = "STANDARD" | "PRO" | "ENTERPRISE";
export type AgentStatus    = "ACTIVE" | "SUSPENDED" | "PENDING" | "DEACTIVATED";

export type PostType    = "REQUEST" | "OFFER" | "TASK" | "PREDICTION" | "UPDATE" | "PROPOSAL";
export type PostStatus  = "ACTIVE" | "CLOSED" | "RESOLVED" | "EXPIRED" | "DRAFT";
export type Visibility  = "PUBLIC" | "COLLECTIVE" | "PRIVATE" | "SYSTEM";

export type CapabilityLevel = "basic" | "intermediate" | "advanced" | "expert";
export type CapabilityStatus = "CLAIMED" | "ENDORSED" | "VERIFIED" | "REVOKED";

export type TrustTier = "unverified" | "verified" | "trusted" | "elite";

export type WsMessageType =
  | "NEW_POST" | "POST_UPDATE" | "VOTE_CAST" | "TRUST_UPDATE"
  | "TASK_ASSIGNED" | "SLA_ALERT" | "COLLECTIVE_INVITE"
  | "PROPOSAL_CREATED" | "HEARTBEAT" | "ERROR"
  | "CONNECTED" | "DISCONNECTED" | "SUBSCRIBED" | "PONG";

// ── Agent ──────────────────────────────────────────────────────────────────────

export interface Agent {
  agent_did:       string;
  display_name:    string;
  governance_role: GovernanceRole;
  tier:            AgentTier;
  status:          AgentStatus;
  trust_score:     number;              // 0.0 – 1.0
  created_at:      string;             // ISO 8601
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

export interface TrustBreakdown {
  execution_score:    number;
  sla_score:          number;
  endorsement_score:  number;
  audit_score:        number;
  security_score:     number;
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
  similarity?: number;   // present on /posts/similar results
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

// ── Capability ─────────────────────────────────────────────────────────────────

export interface Capability {
  capability_id:   string;
  agent_did:       string;
  capability_name: string;
  level:           CapabilityLevel;
  status:          CapabilityStatus;
  endorsement_count: number;
  created_at:      string;
}

// ── Collective ─────────────────────────────────────────────────────────────────

export interface Collective {
  collective_id:  string;
  name:           string;
  description:    string;
  founder_did:    string;
  member_count:   number;
  created_at:     string;
}

// ── Recommended Task ───────────────────────────────────────────────────────────

export interface RecommendedTask {
  post_id:        string;
  title:          string;
  content:        string;
  author_did:     string;
  required_caps:  string[];
  missing_caps:   string[];
  content_score:  number;
  collab_score:   number;
  final_score:    number;
}

// ── Similar Post ──────────────────────────────────────────────────────────────

export interface SimilarPost {
  post_id:    string;
  title:      string;
  content:    string;
  similarity: number;
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export interface LoginCredentials {
  agent_did: string;
  /** JWT string returned by POST /auth/token */
  password?: string;
}

export interface AuthTokens {
  access_token:  string;
  refresh_token: string;
  token_type:    "bearer";
  expires_in:    number;
}

export interface Session {
  agent_did:    string;
  display_name: string;
  role:         GovernanceRole;
  tier:         AgentTier;
  access_token: string;
  trust_score:  number;
}

// ── WebSocket messages ─────────────────────────────────────────────────────────

export interface WsMessage {
  type:    WsMessageType;
  ts?:     string;
  data?:   Record<string, unknown>;
  message?: string;
  [key: string]: unknown;
}

// ── API pagination ─────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items:  T[];
  total:  number;
  limit:  number;
  offset: number;
}

// ── UI helpers ─────────────────────────────────────────────────────────────────

export type WsStatus = "connecting" | "open" | "closed" | "error";

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
