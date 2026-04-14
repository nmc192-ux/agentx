"use client";

/**
 * RoomSidebar — Three collapsible panels:
 *   1. Participants (online status, roles)
 *   2. Artifacts (list with type badges, click to view)
 *   3. Activity log (event stream)
 *
 * Also contains Join / Leave / Close action buttons.
 */
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Users, FileText, Activity, ChevronDown, ChevronRight,
  Plus, LogIn, LogOut, XCircle, Code, FileImage, ScrollText,
  GitBranch, BookOpen, Eye,
} from "lucide-react";
import type { Room, RoomParticipant, Artifact, RoomActivity, ArtifactType } from "@/types";

// ── Constants ───────────────────────────────────────────────────────────────

const ARTIFACT_ICON: Record<ArtifactType, typeof FileText> = {
  NOTE: FileText,
  CODE: Code,
  DIAGRAM: FileImage,
  LOG: ScrollText,
  WORKFLOW: GitBranch,
  RAG_SNIPPET: BookOpen,
};

const ARTIFACT_COLOR: Record<ArtifactType, string> = {
  NOTE: "#3b82f6",
  CODE: "#a855f7",
  DIAGRAM: "#06b6d4",
  LOG: "#22c55e",
  WORKFLOW: "#f59e0b",
  RAG_SNIPPET: "#ef4444",
};

const ROLE_BADGE: Record<string, { label: string; color: string }> = {
  HOST:        { label: "Host", color: "#f59e0b" },
  PARTICIPANT: { label: "Member", color: "#3b82f6" },
  OBSERVER:    { label: "Observer", color: "#64748b" },
};

const ACTION_LABELS: Record<string, string> = {
  joined: "joined the room",
  left: "left the room",
  artifact_added: "added an artifact",
  artifact_removed: "removed an artifact",
  node_created: "placed a node on canvas",
  node_moved: "moved a canvas node",
  node_deleted: "removed a canvas node",
  room_closed: "closed the room",
  room_reopened: "reopened the room",
  message: "sent a message",
};

// ── Types ───────────────────────────────────────────────────────────────────

interface Props {
  room: Room;
  participants: RoomParticipant[];
  artifacts: Artifact[];
  activity: RoomActivity[];
  token: string;
  onJoin: () => void;
  onLeave: () => void;
  onClose: () => void;
  onAddArtifact: () => void;
  onViewArtifact: (artifact: Artifact) => void;
}

// ── Component ───────────────────────────────────────────────────────────────

export function RoomSidebar({
  room, participants, artifacts, activity, token,
  onJoin, onLeave, onClose, onAddArtifact, onViewArtifact,
}: Props) {
  const [openPanel, setOpenPanel] = useState<"participants" | "artifacts" | "activity">("participants");
  const isClosed = room.status === "CLOSED" || room.status === "ARCHIVED";
  const isParticipant = participants.some(
    (p) => token && p.agent_did // simplified — in prod you'd decode the JWT
  );

  return (
    <div className="w-80 border-l border-slate-800 bg-slate-950/80 backdrop-blur-sm flex flex-col overflow-hidden shrink-0">
      {/* Actions */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
        {!isClosed && (
          <>
            <button
              onClick={onJoin}
              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors"
            >
              <LogIn className="w-3 h-3" /> Join
            </button>
            <button
              onClick={onLeave}
              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-slate-800 text-slate-400 hover:bg-slate-700 transition-colors"
            >
              <LogOut className="w-3 h-3" /> Leave
            </button>
            <button
              onClick={onClose}
              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors ml-auto"
            >
              <XCircle className="w-3 h-3" /> Close
            </button>
          </>
        )}
        {isClosed && (
          <span className="text-xs text-slate-500">Room is closed</span>
        )}
      </div>

      {/* Panel tabs */}
      <div className="flex border-b border-slate-800">
        {(["participants", "artifacts", "activity"] as const).map((tab) => {
          const icons = { participants: Users, artifacts: FileText, activity: Activity };
          const Icon = icons[tab];
          const count = tab === "participants" ? participants.length
            : tab === "artifacts" ? artifacts.length
            : activity.length;
          return (
            <button
              key={tab}
              onClick={() => setOpenPanel(tab)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors ${
                openPanel === tab
                  ? "text-cyan-400 border-b-2 border-cyan-400"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
              <span className="text-[10px] bg-slate-800 px-1.5 rounded-full">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto">
        {openPanel === "participants" && (
          <ParticipantsPanel participants={participants} />
        )}
        {openPanel === "artifacts" && (
          <ArtifactsPanel
            artifacts={artifacts}
            onAdd={onAddArtifact}
            onView={onViewArtifact}
            isClosed={isClosed}
          />
        )}
        {openPanel === "activity" && (
          <ActivityPanel activity={activity} />
        )}
      </div>
    </div>
  );
}

// ── Participants panel ──────────────────────────────────────────────────────

function ParticipantsPanel({ participants }: { participants: RoomParticipant[] }) {
  // Sort HOST first, then PARTICIPANT, then OBSERVER
  const sorted = [...participants].sort((a, b) => {
    const order = { HOST: 0, PARTICIPANT: 1, OBSERVER: 2 };
    return (order[a.role] ?? 9) - (order[b.role] ?? 9);
  });

  return (
    <div className="p-3 space-y-1">
      {sorted.length === 0 && (
        <p className="text-xs text-slate-600 text-center py-4">No participants yet</p>
      )}
      {sorted.map((p) => {
        const badge = ROLE_BADGE[p.role] ?? ROLE_BADGE.PARTICIPANT;
        const shortDid = p.agent_did.split(":").pop() ?? p.agent_did;
        return (
          <motion.div
            key={p.agent_did}
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-900/60 transition-colors"
          >
            {/* Avatar circle */}
            <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center text-[10px] font-bold text-slate-400 shrink-0">
              {shortDid.slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-slate-300 truncate">{shortDid}</p>
              <p className="text-[10px] text-slate-600">
                Joined {new Date(p.joined_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </p>
            </div>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ color: badge.color, backgroundColor: `${badge.color}18` }}
            >
              {badge.label}
            </span>
          </motion.div>
        );
      })}
    </div>
  );
}

// ── Artifacts panel ─────────────────────────────────────────────────────────

function ArtifactsPanel({
  artifacts, onAdd, onView, isClosed,
}: {
  artifacts: Artifact[];
  onAdd: () => void;
  onView: (a: Artifact) => void;
  isClosed: boolean;
}) {
  return (
    <div className="p-3 space-y-1">
      {!isClosed && (
        <button
          onClick={onAdd}
          className="w-full flex items-center justify-center gap-1.5 py-2 mb-2 rounded-lg border border-dashed border-slate-700 text-xs text-slate-400 hover:border-cyan-500/40 hover:text-cyan-400 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> Add Artifact
        </button>
      )}

      {artifacts.length === 0 && (
        <p className="text-xs text-slate-600 text-center py-4">No artifacts yet</p>
      )}

      {artifacts.map((a) => {
        const Icon = ARTIFACT_ICON[a.artifact_type] ?? FileText;
        const color = ARTIFACT_COLOR[a.artifact_type] ?? "#3b82f6";
        const shortAuthor = a.author_did.split(":").pop() ?? a.author_did;
        return (
          <motion.button
            key={a.artifact_id}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            onClick={() => onView(a)}
            className="w-full flex items-start gap-2 p-2 rounded-lg hover:bg-slate-900/60 transition-colors text-left group"
          >
            <div className="p-1 rounded" style={{ backgroundColor: `${color}18` }}>
              <Icon className="w-3.5 h-3.5" style={{ color }} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-slate-300 truncate group-hover:text-white transition-colors">
                {a.title || "Untitled"}
              </p>
              <p className="text-[10px] text-slate-600">
                {a.artifact_type} &middot; {shortAuthor} &middot; {timeAgo(a.created_at)}
              </p>
            </div>
            <Eye className="w-3 h-3 text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity mt-1" />
          </motion.button>
        );
      })}
    </div>
  );
}

// ── Activity panel ──────────────────────────────────────────────────────────

function ActivityPanel({ activity }: { activity: RoomActivity[] }) {
  return (
    <div className="p-3 space-y-0.5">
      {activity.length === 0 && (
        <p className="text-xs text-slate-600 text-center py-4">No activity yet</p>
      )}

      {activity.map((a) => {
        const shortDid = a.agent_did.split(":").pop() ?? a.agent_did;
        const actionText = ACTION_LABELS[a.action] ?? a.action;
        return (
          <motion.div
            key={a.activity_id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-start gap-2 py-1.5 px-1"
          >
            <div className="w-1.5 h-1.5 rounded-full bg-slate-600 mt-1.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] text-slate-400">
                <span className="text-slate-300 font-medium">{shortDid}</span>{" "}
                {actionText}
              </p>
              <p className="text-[10px] text-slate-600">{timeAgo(a.created_at)}</p>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
