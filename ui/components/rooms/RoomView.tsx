"use client";

/**
 * RoomView — Full collaboration room experience.
 *
 * Layout:  [ Canvas (flex-1) ]  [ Sidebar (w-80) ]
 *
 * Loads room metadata, participants, artifacts, canvas nodes, and activity.
 * Subscribes to room:{id} WebSocket channel for real-time updates.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Loader2, Users, Wrench, Shield, Eye, Lightbulb,
  Lock,
} from "lucide-react";
import Link from "next/link";
import {
  getRoom, getRoomParticipants, listArtifacts,
  getCanvasNodes, getRoomActivity, joinRoom, leaveRoom, closeRoom,
} from "@/lib/api";
import { agentXWs } from "@/lib/websocket";
import type { WsMessage } from "@/lib/websocket";
import type {
  Room, RoomParticipant, Artifact, CanvasNode, RoomActivity, RoomType,
} from "@/types";
import { RoomCanvas } from "./RoomCanvas";
import { RoomSidebar } from "./RoomSidebar";
import { ArtifactModal } from "./ArtifactModal";

const ROOM_ICON: Record<RoomType, typeof Wrench> = {
  WORKSHOP: Wrench, WAR_ROOM: Shield, REVIEW: Eye, BRAINSTORM: Lightbulb,
};
const ROOM_COLOR: Record<RoomType, string> = {
  WORKSHOP: "#3B82F6", WAR_ROOM: "#EF4444", REVIEW: "#F59E0B", BRAINSTORM: "#A855F7",
};

interface Props { roomId: string }

export function RoomView({ roomId }: Props) {
  // ── State ────────────────────────────────────────────────────────────────
  const [room, setRoom] = useState<Room | null>(null);
  const [participants, setParticipants] = useState<RoomParticipant[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [canvasNodes, setCanvasNodes] = useState<CanvasNode[]>([]);
  const [activity, setActivity] = useState<RoomActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Artifact modal
  const [artifactModalOpen, setArtifactModalOpen] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);

  const token = typeof window !== "undefined"
    ? localStorage.getItem("agentx_token") ?? ""
    : "";

  // ── Data fetching ────────────────────────────────────────────────────────
  const fetchAll = useCallback(async () => {
    try {
      const [r, p, a, cn, act] = await Promise.all([
        getRoom(roomId, token),
        getRoomParticipants(roomId, token),
        listArtifacts(roomId, 100, token),
        getCanvasNodes(roomId, token),
        getRoomActivity(roomId, 50, token),
      ]);
      setRoom(r);
      setParticipants(p);
      setArtifacts(a);
      setCanvasNodes(cn);
      setActivity(act);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load room");
    } finally {
      setLoading(false);
    }
  }, [roomId, token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // ── WebSocket subscription ───────────────────────────────────────────────
  useEffect(() => {
    if (!token) return;
    const channel = `room:${roomId}`;
    agentXWs.connect(token);
    agentXWs.subscribe(channel);

    const handler = (msg: WsMessage) => {
      if (msg.type === "ROOM_UPDATE") {
        // Re-fetch participants and room on join/leave/close
        getRoom(roomId, token).then(setRoom).catch(() => {});
        getRoomParticipants(roomId, token).then(setParticipants).catch(() => {});
        getRoomActivity(roomId, 10, token).then((a) =>
          setActivity((prev) => {
            const ids = new Set(prev.map((p) => p.activity_id));
            const fresh = a.filter((x) => !ids.has(x.activity_id));
            return [...fresh, ...prev].slice(0, 100);
          })
        ).catch(() => {});
      }
      if (msg.type === "ARTIFACT_ADDED") {
        listArtifacts(roomId, 100, token).then(setArtifacts).catch(() => {});
        getCanvasNodes(roomId, token).then(setCanvasNodes).catch(() => {});
        getRoomActivity(roomId, 5, token).then((a) =>
          setActivity((prev) => {
            const ids = new Set(prev.map((p) => p.activity_id));
            const fresh = a.filter((x) => !ids.has(x.activity_id));
            return [...fresh, ...prev].slice(0, 100);
          })
        ).catch(() => {});
      }
      if (
        msg.type === "CANVAS_NODE_CREATED" ||
        msg.type === "CANVAS_NODE_MOVED" ||
        msg.type === "CANVAS_NODE_DELETED" ||
        msg.type === "CANVAS_BATCH_MOVED"
      ) {
        getCanvasNodes(roomId, token).then(setCanvasNodes).catch(() => {});
      }
    };

    agentXWs.onMessage(handler);
    return () => { agentXWs.offMessage(handler); };
  }, [roomId, token]);

  // ── Handlers ─────────────────────────────────────────────────────────────
  async function handleJoin() {
    if (!token) return;
    try {
      await joinRoom(roomId, token);
      fetchAll();
    } catch { /* already in */ }
  }

  async function handleLeave() {
    if (!token) return;
    try {
      await leaveRoom(roomId, token);
      fetchAll();
    } catch { /* not in */ }
  }

  async function handleClose() {
    if (!token) return;
    try {
      const updated = await closeRoom(roomId, token);
      setRoom(updated);
    } catch { /* not host */ }
  }

  function handleArtifactCreated() {
    listArtifacts(roomId, 100, token).then(setArtifacts).catch(() => {});
    getCanvasNodes(roomId, token).then(setCanvasNodes).catch(() => {});
    getRoomActivity(roomId, 5, token).then((a) =>
      setActivity((prev) => [...a.filter((x) => !prev.some((p) => p.activity_id === x.activity_id)), ...prev].slice(0, 100))
    ).catch(() => {});
  }

  function handleViewArtifact(artifact: Artifact) {
    setSelectedArtifact(artifact);
    setArtifactModalOpen(true);
  }

  // ── Render ───────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !room) {
    return (
      <div className="text-center py-16">
        <p className="text-red-400">{error ?? "Room not found"}</p>
        <Link href="/rooms" className="text-cyan-400 text-sm mt-2 inline-block hover:underline">
          Back to rooms
        </Link>
      </div>
    );
  }

  const Icon = ROOM_ICON[room.room_type] ?? Wrench;
  const color = ROOM_COLOR[room.room_type] ?? "#3B82F6";
  const isClosed = room.status === "CLOSED" || room.status === "ARCHIVED";

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-slate-950/60 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/rooms" className="text-slate-500 hover:text-slate-300 transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="p-1.5 rounded-lg" style={{ backgroundColor: `${color}18` }}>
            <Icon className="w-4 h-4" style={{ color }} />
          </div>
          <div>
            <h1 className="text-sm font-semibold leading-tight">{room.name}</h1>
            <span className="text-xs text-slate-500">{room.room_type.replace("_", " ")}</span>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ml-2 ${
            room.status === "OPEN" ? "bg-green-500/10 text-green-400" :
            room.status === "IN_PROGRESS" ? "bg-blue-500/10 text-blue-400" :
            "bg-slate-800 text-slate-500"
          }`}>
            {room.status}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 flex items-center gap-1">
            <Users className="w-3 h-3" />
            {participants.length}/{room.max_participants}
          </span>
          {isClosed && (
            <span className="flex items-center gap-1 text-xs text-slate-600">
              <Lock className="w-3 h-3" /> Closed
            </span>
          )}
        </div>
      </div>

      {/* Main content: Canvas + Sidebar */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 relative">
          <RoomCanvas
            roomId={roomId}
            nodes={canvasNodes}
            artifacts={artifacts}
            token={token}
            readOnly={isClosed}
            onNodesChanged={() => getCanvasNodes(roomId, token).then(setCanvasNodes).catch(() => {})}
          />
        </div>
        <RoomSidebar
          room={room}
          participants={participants}
          artifacts={artifacts}
          activity={activity}
          token={token}
          onJoin={handleJoin}
          onLeave={handleLeave}
          onClose={handleClose}
          onAddArtifact={() => { setSelectedArtifact(null); setArtifactModalOpen(true); }}
          onViewArtifact={handleViewArtifact}
        />
      </div>

      {/* Artifact modal */}
      <AnimatePresence>
        {artifactModalOpen && (
          <ArtifactModal
            roomId={roomId}
            artifact={selectedArtifact}
            token={token}
            onClose={() => setArtifactModalOpen(false)}
            onCreated={handleArtifactCreated}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
