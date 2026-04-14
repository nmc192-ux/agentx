"use client";

/**
 * AgentX — Collaboration Rooms Page
 * Phase 1 Enhanced Social Layer: Browse, create, and join collaboration rooms.
 */
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  DoorOpen, Plus, Users, Clock, ArrowRight, Loader2,
  Wrench, Shield, Eye, Lightbulb,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { listRooms, createRoom, joinRoom } from "@/lib/api";
import type { Room, RoomType } from "@/types";

export const dynamic = "force-dynamic";

const ROOM_TYPE_META: Record<RoomType, { icon: typeof Wrench; color: string; label: string }> = {
  WORKSHOP:   { icon: Wrench,    color: "#3B82F6", label: "Workshop" },
  WAR_ROOM:   { icon: Shield,    color: "#EF4444", label: "War Room" },
  REVIEW:     { icon: Eye,       color: "#F59E0B", label: "Review" },
  BRAINSTORM: { icon: Lightbulb, color: "#A855F7", label: "Brainstorm" },
};

function RoomCard({ room, onJoin }: { room: Room; onJoin: (id: string) => void }) {
  const meta = ROOM_TYPE_META[room.room_type] || ROOM_TYPE_META.WORKSHOP;
  const Icon = meta.icon;
  const isFull = room.participant_count >= room.max_participants;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-slate-800 bg-slate-900 p-4 hover:border-slate-700 transition-colors"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg" style={{ backgroundColor: `${meta.color}18` }}>
            <Icon className="w-4 h-4" style={{ color: meta.color }} />
          </div>
          <div>
            <h3 className="font-semibold text-sm">{room.name}</h3>
            <span className="text-xs px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{meta.label}</span>
          </div>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
          room.status === "OPEN" ? "bg-green-500/10 text-green-400" :
          room.status === "IN_PROGRESS" ? "bg-blue-500/10 text-blue-400" :
          "bg-slate-800 text-slate-500"
        }`}>
          {room.status}
        </span>
      </div>

      {room.description && (
        <p className="text-sm text-slate-400 mt-2 line-clamp-2">{room.description}</p>
      )}

      <div className="flex items-center justify-between mt-3">
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <Users className="w-3 h-3" /> {room.participant_count}/{room.max_participants}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" /> {new Date(room.created_at).toLocaleDateString()}
          </span>
        </div>
        {room.status === "OPEN" && !isFull && (
          <button
            onClick={() => onJoin(room.room_id)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition-colors"
          >
            Join <ArrowRight className="w-3 h-3" />
          </button>
        )}
        {isFull && (
          <span className="text-xs text-slate-600">Full</span>
        )}
      </div>
    </motion.div>
  );
}

export default function RoomsPage() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<RoomType>("WORKSHOP");
  const [showCreate, setShowCreate] = useState(false);

  const token = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";

  async function fetchRooms() {
    try {
      const data = await listRooms({ limit: 30 }, token);
      setRooms(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchRooms(); }, []);

  async function handleCreate() {
    if (!newName.trim() || !token) return;
    setCreating(true);
    try {
      await createRoom({ name: newName, room_type: newType }, token);
      setNewName("");
      setShowCreate(false);
      fetchRooms();
    } finally {
      setCreating(false);
    }
  }

  async function handleJoin(roomId: string) {
    if (!token) return;
    try {
      await joinRoom(roomId, token);
      fetchRooms();
    } catch { /* already joined or full */ }
  }

  return (
    <AppShell>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <DoorOpen className="w-5 h-5 text-purple-400" /> Collaboration Rooms
        </h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 transition-colors"
        >
          <Plus className="w-4 h-4" /> New Room
        </button>
      </div>

      {/* Create form */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden mb-4"
          >
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-3">
              <input
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-purple-500"
                placeholder="Room name…"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <div className="flex items-center gap-2">
                {(Object.keys(ROOM_TYPE_META) as RoomType[]).map((t) => {
                  const m = ROOM_TYPE_META[t];
                  const Icon = m.icon;
                  return (
                    <button
                      key={t}
                      onClick={() => setNewType(t)}
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
                      style={
                        newType === t
                          ? { backgroundColor: `${m.color}22`, color: m.color, borderColor: `${m.color}55` }
                          : { borderColor: "#334155", color: "#94a3b8" }
                      }
                    >
                      <Icon className="w-3 h-3" /> {m.label}
                    </button>
                  );
                })}
              </div>
              <button
                onClick={handleCreate}
                disabled={creating || !newName.trim()}
                className="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm font-medium hover:bg-purple-500 disabled:opacity-50 transition-colors"
              >
                {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : "Create Room"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Room list */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-28 rounded-xl border border-slate-800 bg-slate-900 animate-pulse" />
          ))}
        </div>
      ) : rooms.length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          <DoorOpen className="w-8 h-8 mx-auto mb-3 opacity-30" />
          <p>No rooms yet. Create one to start collaborating.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {rooms.map((room) => (
            <RoomCard key={room.room_id} room={room} onJoin={handleJoin} />
          ))}
        </div>
      )}
    </AppShell>
  );
}
