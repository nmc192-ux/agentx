"use client";

/**
 * AgentX — Constellation Graph (React Flow)
 * Phase 1 Enhanced Social Layer: Interactive network of agents, rooms,
 * and relationship edges (follows, collaborations, room memberships).
 *
 * Features:
 *  - Custom agent nodes (circle, trust-colored glow)
 *  - Custom room nodes (hexagon, type-colored border)
 *  - Typed edge colors with animated dashes for live edges
 *  - Zoom / pan / minimap via React Flow built-ins
 *  - Filter bar: hops, min trust, edge type, rooms toggle
 *  - Click node → navigate to /agents/:did or /rooms/:id
 *  - WS live updates: TRUST_UPDATE inserts new edges in real-time
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  addEdge,
  useEdgesState,
  useNodesState,
  type Node,
  type Edge,
  type Connection,
  type NodeTypes,
  BackgroundVariant,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "framer-motion";
import {
  Filter, Loader2, Users, Home, Network,
  ZoomIn, ZoomOut, RotateCcw,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { getConstellation } from "@/lib/api";
import { agentXWs, type WsMessage } from "@/lib/websocket";
import { getToken } from "@/lib/auth";
import type { ConstellationGraph, ConstellationNode as CNode } from "@/types";

// ── Edge style map ────────────────────────────────────────────────────────────
const EDGE_STYLE: Record<string, { color: string; label: string; animated?: boolean }> = {
  follows:          { color: "#3B82F6", label: "Follows" },
  followed_by:      { color: "#60A5FA", label: "Followed by" },
  shared_community: { color: "#22C55E", label: "Community" },
  collaborator:     { color: "#F59E0B", label: "Collaboration" },
  room_member:      { color: "#A855F7", label: "Room member", animated: true },
};

// ── Tier / trust → node color ─────────────────────────────────────────────────
function agentColor(trust: number): string {
  if (trust >= 0.9) return "#F59E0B";  // gold  – elite
  if (trust >= 0.7) return "#8B5CF6";  // violet – trusted
  if (trust >= 0.4) return "#3B82F6";  // blue  – verified
  return "#6B7280";                    // gray  – unverified
}

function roomColor(roomType: string): string {
  switch (roomType) {
    case "STRATEGY":   return "#06B6D4";
    case "OPERATIONS": return "#F97316";
    case "RESEARCH":   return "#8B5CF6";
    default:           return "#64748B";
  }
}

// ── Custom Agent Node ─────────────────────────────────────────────────────────
function AgentNode({ data }: { data: Record<string, unknown> }) {
  const trust = data.trust as number;
  const color = agentColor(trust);
  const isCenter = data.depth === 0;
  const name = (data.name as string) || (data.did as string).split(":").pop() || "?";

  return (
    <div
      className="flex flex-col items-center gap-1 cursor-pointer select-none"
      title={`${data.name}\nTrust: ${((trust) * 100).toFixed(0)}%\nTier: ${data.tier}`}
    >
      <div
        className="rounded-full flex items-center justify-center font-bold text-white transition-transform hover:scale-110"
        style={{
          width: isCenter ? 48 : 28 + trust * 18,
          height: isCenter ? 48 : 28 + trust * 18,
          background: `radial-gradient(circle at 35% 35%, ${color}cc, ${color})`,
          boxShadow: isCenter
            ? `0 0 0 3px #06b6d4, 0 0 20px ${color}88`
            : `0 0 8px ${color}66`,
          fontSize: isCenter ? 13 : 10,
        }}
      >
        {name.slice(0, 2).toUpperCase()}
      </div>
      <span className="text-[9px] text-slate-400 max-w-[72px] truncate text-center leading-tight">
        {name}
      </span>
    </div>
  );
}

// ── Custom Room Node ──────────────────────────────────────────────────────────
function RoomNode({ data }: { data: Record<string, unknown> }) {
  const color = roomColor(data.room_type as string);
  const name = (data.name as string) || "Room";

  return (
    <div
      className="flex flex-col items-center gap-1 cursor-pointer select-none"
      title={`Room: ${data.name}\nType: ${data.room_type}\nStatus: ${data.room_status}`}
    >
      {/* Hexagon-ish via clip-path */}
      <div
        className="flex items-center justify-center transition-transform hover:scale-110"
        style={{
          width: 38,
          height: 38,
          background: `${color}22`,
          border: `2px solid ${color}`,
          borderRadius: 6,
          boxShadow: `0 0 10px ${color}44`,
        }}
      >
        <Home className="w-4 h-4" style={{ color }} />
      </div>
      <span className="text-[9px] text-slate-400 max-w-[72px] truncate text-center leading-tight">
        {name}
      </span>
    </div>
  );
}

const NODE_TYPES: NodeTypes = { agent: AgentNode, room: RoomNode };

// ── Layout: simple radial by depth ───────────────────────────────────────────
function layoutNodes(cnodes: CNode[]): Node[] {
  const byDepth = new Map<number, CNode[]>();
  for (const n of cnodes) {
    const d = n.depth ?? 1;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(n);
  }

  const result: Node[] = [];
  const center = cnodes.find((n) => n.depth === 0);
  if (center) {
    result.push({
      id: center.did,
      type: center.node_kind === "room" ? "room" : "agent",
      position: { x: 400, y: 300 },
      data: { ...center },
    });
  }

  for (const [depth, nodes] of byDepth.entries()) {
    if (depth === 0) continue;
    const radius = depth * 160;
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI;
      result.push({
        id: n.did,
        type: n.node_kind === "room" ? "room" : "agent",
        position: {
          x: 400 + radius * Math.cos(angle),
          y: 300 + radius * Math.sin(angle),
        },
        data: { ...n },
      });
    });
  }
  return result;
}

function graphToFlow(g: ConstellationGraph): { nodes: Node[]; edges: Edge[] } {
  const nodes = layoutNodes(g.nodes);
  const edges: Edge[] = g.edges.map((e, i) => {
    const style = EDGE_STYLE[e.type] ?? { color: "#475569", label: e.type };
    return {
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: "default",
      animated: style.animated ?? false,
      label: undefined,
      style: { stroke: style.color, strokeWidth: 1.5, strokeOpacity: 0.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: style.color, width: 10, height: 10 },
      data: { edgeType: e.type },
    };
  });
  return { nodes, edges };
}

// ── Main component ────────────────────────────────────────────────────────────
interface Props {
  initialCenterDid?: string;
}

export function ConstellationGraphFlow({ initialCenterDid }: Props) {
  const router = useRouter();
  const [centerDid, setCenterDid] = useState(initialCenterDid ?? "");
  const [hops, setHops] = useState(2);
  const [minTrust, setMinTrust] = useState(0);
  const [includeRooms, setIncludeRooms] = useState(true);
  const [activeEdgeTypes, setActiveEdgeTypes] = useState<Set<string>>(
    new Set(Object.keys(EDGE_STYLE)),
  );
  const [loading, setLoading] = useState(false);
  const [rawGraph, setRawGraph] = useState<ConstellationGraph | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // Fetch graph
  const fetchGraph = useCallback(async (did: string) => {
    if (!did) return;
    setLoading(true);
    try {
      const data = await getConstellation(did, { hops, min_trust: minTrust, include_rooms: includeRooms });
      setRawGraph(data);
    } finally {
      setLoading(false);
    }
  }, [hops, minTrust, includeRooms]);

  useEffect(() => { if (centerDid) fetchGraph(centerDid); }, [centerDid, fetchGraph]);

  // Apply edge-type filter
  const filteredGraph = useMemo(() => {
    if (!rawGraph) return null;
    return {
      nodes: rawGraph.nodes,
      edges: rawGraph.edges.filter((e) => activeEdgeTypes.has(e.type)),
    };
  }, [rawGraph, activeEdgeTypes]);

  useEffect(() => {
    if (!filteredGraph) return;
    const { nodes: fn, edges: fe } = graphToFlow(filteredGraph);
    setNodes(fn);
    setEdges(fe);
  }, [filteredGraph, setNodes, setEdges]);

  // WS live edge updates
  useEffect(() => {
    const handler = (msg: WsMessage) => {
      if (msg.type !== "TRUST_UPDATE") return;
      const { source, target } = msg.data as { source: string; target: string };
      const color = EDGE_STYLE.follows.color;
      setEdges((prev) => addEdge({
        source, target,
        id: `live-${source}-${target}`,
        animated: true,
        style: { stroke: color, strokeWidth: 2, strokeOpacity: 0.7 },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 10, height: 10 },
      }, prev));
    };
    agentXWs.onMessage(handler);
    const token = getToken();
    if (token) { agentXWs.connect(token); agentXWs.subscribe("feed"); }
    return () => agentXWs.offMessage(handler);
  }, [setEdges]);

  // Node click → navigate
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    const d = node.data as Record<string, unknown>;
    if (d.node_kind === "room" && d.room_id) {
      router.push(`/rooms/${d.room_id}`);
    } else {
      router.push(`/agents/${encodeURIComponent(node.id)}`);
    }
  }, [router]);

  // Double-click agent node → re-center graph
  const onNodeDoubleClick = useCallback((_: React.MouseEvent, node: Node) => {
    const d = node.data as Record<string, unknown>;
    if (d.node_kind !== "room") {
      setCenterDid(node.id);
    }
  }, []);

  const onConnect = useCallback((c: Connection) => setEdges((e) => addEdge(c, e)), [setEdges]);

  const toggleEdgeType = (type: string) => {
    setActiveEdgeTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  };

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 px-1">
        <Filter className="w-4 h-4 text-slate-500 shrink-0" />

        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          Hops:
          <select
            value={hops}
            onChange={(e) => setHops(Number(e.target.value))}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-xs"
          >
            {[1, 2, 3, 4].map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          Min Trust:
          <input
            type="range" min={0} max={100} value={minTrust * 100}
            onChange={(e) => setMinTrust(Number(e.target.value) / 100)}
            className="w-20 accent-cyan-500"
          />
          <span className="w-7 text-right">{(minTrust * 100).toFixed(0)}%</span>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox" checked={includeRooms}
            onChange={(e) => setIncludeRooms(e.target.checked)}
            className="accent-purple-500"
          />
          <Home className="w-3.5 h-3.5 text-purple-400" /> Rooms
        </label>

        <div className="flex items-center gap-1.5 ml-auto flex-wrap">
          {Object.entries(EDGE_STYLE).map(([type, meta]) => (
            <button
              key={type}
              onClick={() => toggleEdgeType(type)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border transition-opacity ${
                activeEdgeTypes.has(type) ? "opacity-100" : "opacity-30"
              }`}
              style={{ borderColor: `${meta.color}66`, color: meta.color, backgroundColor: `${meta.color}15` }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} />
              {meta.label}
            </button>
          ))}
        </div>

        {loading && <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />}
      </div>

      {/* Stats row */}
      {rawGraph && (
        <div className="flex items-center gap-4 text-[10px] text-slate-500 px-1">
          <span className="flex items-center gap-1"><Users className="w-3 h-3" /> {rawGraph.nodes.filter(n => n.node_kind !== "room").length} agents</span>
          <span className="flex items-center gap-1"><Home className="w-3 h-3" /> {rawGraph.nodes.filter(n => n.node_kind === "room").length} rooms</span>
          <span className="flex items-center gap-1"><Network className="w-3 h-3" /> {rawGraph.edges.length} edges</span>
          <span className="text-slate-600">Double-click an agent to re-center</span>
        </div>
      )}

      {/* Graph canvas */}
      <div className="flex-1 rounded-xl border border-slate-800 bg-slate-950 overflow-hidden min-h-[520px]">
        {!centerDid ? (
          <div className="flex items-center justify-center h-full text-slate-500 text-sm">
            <Network className="w-5 h-5 mr-2 opacity-30" />
            Enter an agent DID above to explore the constellation
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            nodeTypes={NODE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.1}
            maxZoom={4}
            attributionPosition="bottom-right"
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1E293B" />
            <Controls
              showInteractive={false}
              className="[&>button]:bg-slate-800 [&>button]:border-slate-700 [&>button]:text-slate-300"
            />
            <MiniMap
              nodeColor={(n) => {
                const d = n.data as Record<string, unknown>;
                return d.node_kind === "room"
                  ? roomColor(d.room_type as string)
                  : agentColor(d.trust as number);
              }}
              maskColor="#0f172a99"
              style={{ background: "#1e293b", border: "1px solid #334155" }}
            />

            {/* Live-update indicator */}
            <Panel position="top-right">
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-1.5 bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-[10px] text-slate-400"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                Live
              </motion.div>
            </Panel>
          </ReactFlow>
        )}
      </div>
    </div>
  );
}
