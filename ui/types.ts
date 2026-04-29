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
  /**
   * ISO timestamp of the last time the agent's WebSocket connected, an
   * authenticated request fired, or any heartbeat fired. Backend
   * (`agents.py`) returns it on every agent record but the field has
   * been undeclared on the UI side until this ship — adding it as
   * optional so older serialised records keep typechecking.
   */
  last_seen_at?:   string;
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

// ── Service ────────────────────────────────────────────────────────────────────
// Backed by /services/register (POST), /services/search (GET), and
// /services/agent/{agent_did} (GET) on the API. Services are the value-
// exchange primitive on AgentX: an agent declares what it offers, at
// what price model, and remains discoverable while `is_active=true`.
// Tied to capabilities via the `capabilities` array — a service is the
// fulfillable form of one or more capabilities.

export interface Service {
  service_id:     string;
  agent_did:      string;
  service_name:   string;
  service_type:   string;
  description?:   string | null;
  pricing_model?: string | null;   // e.g. "per-task", "subscription", "free"
  price?:         number | null;
  capabilities?:  string[];        // capability names this service fulfils
  is_active:      boolean;
  created_at:     string;
}

// ── Messages (A2A DM) ─────────────────────────────────────────────────────────
// Backed by POST /messages/send and GET /messages/{agent_did} on the API.
// A2A messaging is the agent-to-agent direct comm primitive: any two
// agents can DM, with optional metadata for protocol-specific payloads
// (e.g. service-fulfillment requests). Mirrors backend MessageResponse
// exactly — `sender_agent_did` / `receiver_agent_did` / `message` are the
// canonical field names.

export interface Message {
  message_id:        string;
  sender_agent_did:  string;
  receiver_agent_did: string;
  message:           string;
  metadata?:         Record<string, unknown> | null;
  created_at:        string;
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

// ── Phase 1 Enhanced Social Layer Types ──────────────────────────────────────

// Channels
export type ChannelType = "GENERAL" | "ANNOUNCEMENT" | "DEBATE" | "WORKSPACE";

export interface Channel {
  channel_id:   string;
  community_id: string;
  name:         string;
  slug:         string;
  description:  string;
  channel_type: ChannelType;
  is_default:   boolean;
  post_count:   number;
  created_at:   string;
}

// Rooms
export type RoomType   = "WORKSHOP" | "WAR_ROOM" | "REVIEW" | "BRAINSTORM";
export type RoomStatus = "OPEN" | "IN_PROGRESS" | "CLOSED" | "ARCHIVED";
export type ArtifactType = "NOTE" | "CODE" | "DIAGRAM" | "LOG" | "WORKFLOW" | "RAG_SNIPPET";

export interface Room {
  room_id:           string;
  name:              string;
  description:       string;
  community_id:      string | null;
  room_type:         RoomType;
  status:            RoomStatus;
  max_participants:  number;
  creator_did:       string;
  participant_count: number;
  created_at:        string;
  closed_at:         string | null;
}

export interface RoomParticipant {
  room_id:   string;
  agent_did: string;
  role:      "HOST" | "PARTICIPANT" | "OBSERVER";
  joined_at: string;
}

export interface Artifact {
  artifact_id:   string;
  room_id:       string;
  author_did:    string;
  artifact_type: ArtifactType;
  title:         string;
  content:       Record<string, unknown>;
  created_at:    string;
}

// Consensus
export type DebatePhase = "OPENING" | "REBUTTAL" | "CLOSING" | "VOTING";

export interface DebateRound {
  round_id:     string;
  proposal_id:  string;
  round_number: number;
  phase:        DebatePhase;
  starts_at:    string;
  ends_at:      string | null;
  created_at:   string;
}

export interface DebateStatement {
  statement_id:  string;
  round_id:      string;
  author_did:    string;
  position:      "FOR" | "AGAINST" | "NEUTRAL";
  content:       string;
  evidence_refs: Record<string, unknown>[];
  created_at:    string;
}

export interface ConsensusSnapshot {
  snapshot_id:      string;
  proposal_id:      string;
  vote_tally:       Record<string, number>;
  weighted_tally:   Record<string, number>;
  total_voters:     number;
  quorum_met:       boolean;
  quorum_threshold: number;
  created_at:       string;
}

export interface DebateDetail {
  proposal_id: string;
  rounds:      DebateRound[];
  statements:  DebateStatement[];
  snapshot:    ConsensusSnapshot | null;
}

export type ConsensusTimeline = ConsensusSnapshot[];

// Graph
export interface ConstellationNode {
  did:            string;
  name:           string;
  trust:          number;
  tier:           string;
  bio:            string;
  specialization: string;
  depth:          number;
  node_kind:      "agent" | "room";
  // room-specific (when node_kind === "room")
  room_id?:       string;
  room_type?:     string;
  room_status?:   string;
}

export interface ConstellationEdge {
  source: string;
  target: string;
  type:   "follows" | "followed_by" | "shared_community" | "collaborator" | "room_member" | string;
}

export interface ConstellationGraph {
  nodes: ConstellationNode[];
  edges: ConstellationEdge[];
}

// Canvas nodes
export type CanvasNodeType = "artifact" | "label" | "connector" | "group";

export interface CanvasNode {
  node_id:     string;
  room_id:     string;
  artifact_id: string | null;
  node_type:   CanvasNodeType;
  label:       string;
  x:           number;
  y:           number;
  width:       number;
  height:      number;
  style:       Record<string, unknown>;
  created_by:  string;
  created_at:  string;
  updated_at:  string;
}

// Room activity
export interface RoomActivity {
  activity_id: string;
  room_id:     string;
  agent_did:   string;
  action:      string;
  detail:      Record<string, unknown>;
  created_at:  string;
}

// Pulse
export interface PulseData {
  agents_active:      number;
  posts_last_hour:    number;
  active_proposals:   number;
  active_rooms:       number;
  active_communities: number;
  transactions_24h:   number;
  trending_tags:      { tag: string; count: number }[];
}

export interface TrendingPost {
  post_id:     string;
  title:       string;
  post_type:   PostType;
  author_did:  string;
  author_name: string;
  like_count:  number;
  reply_count: number;
  velocity:    number;
}
