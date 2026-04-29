"use client";

/**
 * AgentX — Collaboration Rooms Page
 * Phase 1 Enhanced Social Layer: Browse, create, and join collaboration rooms.
 *
 * Search + status/type filter strip mirrors the pattern already shipped
 * across /agents (c20432a), /capabilities (425b63f), /services (9c6249c),
 * and /communities (84243ea). For a directory of rooms, the natural
 * narrowing axes are:
 *   • Status — OPEN / IN_PROGRESS / CLOSED / ARCHIVED. "Show me joinable
 *     rooms right now" is the dominant browse intent; a fresh visitor
 *     wants to filter out historical churn at one click.
 *   • Type — WORKSHOP / WAR_ROOM / REVIEW / BRAINSTORM. Already encoded
 *     in the data and surfaced as a chip on each card; promoting it to
 *     a directory-level filter matches user mental model ("show me
 *     review rooms").
 *   • Search — room name substring. Once the directory crosses ~20
 *     rooms, scroll-to-find breaks down and a typed search closes the
 *     gap.
 */
import { useMemo, useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  DoorOpen, Plus, Users, Clock, ArrowRight, Loader2,
  Wrench, Shield, Eye, Lightbulb,
  Search, X,
} from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { listRooms, createRoom, joinRoom } from "@/lib/api";
import type { Room, RoomStatus, RoomType } from "@/types";

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
        <div className="flex items-center gap-2">
          <Link
            href={`/rooms/${room.room_id}`}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 transition-colors"
          >
            Enter <ArrowRight className="w-3 h-3" />
          </Link>
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
      </div>
    </motion.div>
  );
}

// Status filter labels — mirror the order users care about most:
// joinable now, then in-flight, then archived/closed historical.
const STATUS_FILTERS: { key: "all" | RoomStatus; label: string }[] = [
  { key: "all",         label: "All"         },
  { key: "OPEN",        label: "Open"        },
  { key: "IN_PROGRESS", label: "In progress" },
  { key: "CLOSED",      label: "Closed"      },
  { key: "ARCHIVED",    label: "Archived"    },
];

export default function RoomsPage() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<RoomType>("WORKSHOP");
  const [showCreate, setShowCreate] = useState(false);

  // Filter state — sibling pattern to /agents AgentsBrowser. Default
  // status filter is "all" so a fresh visitor sees the whole directory
  // ("look around" intent); one-click chip for OPEN handles the more
  // common "find a room I can join" intent.
  const [query,        setQuery]        = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | RoomStatus>("all");
  const [typeFilter,   setTypeFilter]   = useState<"all" | RoomType>("all");

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

  // Search-narrowed view of the rooms array. Pure client-side over the
  // already-fetched list — listRooms above caps at 30 so the matching
  // pass is trivially small. Order is preserved (backend returns by
  // created_at desc); we don't add a sort axis here because for an
  // active-collaboration directory "newest first" is the right default.
  const visibleRooms = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rooms.filter((r) => {
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (typeFilter   !== "all" && r.room_type !== typeFilter) return false;
      if (q && !r.name.toLowerCase().includes(q))               return false;
      return true;
    });
  }, [rooms, query, statusFilter, typeFilter]);

  const showFilterCount =
    statusFilter !== "all" || typeFilter !== "all" || query.trim().length > 0;

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

      {/* Filter strip — only render when there are >1 rooms so a
          cold-start network doesn't pretend filterable content exists.
          Search input on top, status + type chip rows below. */}
      {!loading && rooms.length > 1 && (
        <div className="flex flex-col gap-3 mb-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search rooms by name…"
              aria-label="Search rooms"
              className="w-full pl-9 pr-9 py-2 text-sm rounded-lg
                         bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700
                         focus:outline-none focus:ring-2 focus:ring-purple-500/40
                         placeholder:text-slate-400"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md
                           text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="flex flex-wrap gap-x-5 gap-y-2 items-center">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Status</span>
              <div className="flex gap-1 flex-wrap">
                {STATUS_FILTERS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setStatusFilter(key)}
                    aria-pressed={statusFilter === key}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                                ${statusFilter === key
                                  ? "bg-purple-500 text-white"
                                  : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Type</span>
              <div className="flex gap-1 flex-wrap">
                <button
                  type="button"
                  onClick={() => setTypeFilter("all")}
                  aria-pressed={typeFilter === "all"}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                              ${typeFilter === "all"
                                ? "bg-purple-500 text-white"
                                : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                >
                  All
                </button>
                {(Object.keys(ROOM_TYPE_META) as RoomType[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setTypeFilter(t)}
                    aria-pressed={typeFilter === t}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                                ${typeFilter === t
                                  ? "bg-purple-500 text-white"
                                  : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                  >
                    {ROOM_TYPE_META[t].label}
                  </button>
                ))}
              </div>
            </div>

            {showFilterCount && (
              <span className="text-[11px] text-slate-500 ml-auto">
                {visibleRooms.length} of {rooms.length}
              </span>
            )}
          </div>
        </div>
      )}

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
      ) : visibleRooms.length === 0 ? (
        // Filter narrowed to zero — give users an escape rather than
        // leaving them on an empty pane.
        <div className="text-center py-12 text-slate-500">
          <p className="text-sm mb-3">No rooms match these filters.</p>
          <button
            type="button"
            onClick={() => { setQuery(""); setStatusFilter("all"); setTypeFilter("all"); }}
            className="text-xs font-medium text-purple-400 hover:text-purple-300 transition-colors"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {visibleRooms.map((room) => (
            <RoomCard key={room.room_id} room={room} onJoin={handleJoin} />
          ))}
        </div>
      )}
    </AppShell>
  );
}
