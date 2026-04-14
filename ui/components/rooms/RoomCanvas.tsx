"use client";

/**
 * RoomCanvas — Interactive D3 canvas with draggable artifact nodes.
 *
 * Each CanvasNode renders as a styled rectangle with the artifact title,
 * type icon, and author badge. Nodes are draggable; on drag-end the new
 * position is PATCH'd to the server and broadcast to other participants.
 *
 * Supports zoom/pan via D3 zoom behaviour.
 */
import { useRef, useEffect, useCallback, useState } from "react";
import * as d3 from "d3";
import { updateCanvasNode, createCanvasNode } from "@/lib/api";
import type { CanvasNode, Artifact, ArtifactType } from "@/types";

// ── Constants ───────────────────────────────────────────────────────────────

const ARTIFACT_COLORS: Record<ArtifactType, { bg: string; border: string; text: string }> = {
  NOTE:        { bg: "#1e293b", border: "#3b82f6", text: "#93c5fd" },
  CODE:        { bg: "#1a1a2e", border: "#a855f7", text: "#c4b5fd" },
  DIAGRAM:     { bg: "#1a2332", border: "#06b6d4", text: "#67e8f9" },
  LOG:         { bg: "#1a2318", border: "#22c55e", text: "#86efac" },
  WORKFLOW:    { bg: "#231a18", border: "#f59e0b", text: "#fcd34d" },
  RAG_SNIPPET: { bg: "#23181a", border: "#ef4444", text: "#fca5a5" },
};

const NODE_TYPE_ICONS: Record<string, string> = {
  artifact:  "\u25A3",   // filled square with inner square
  label:     "\u2630",   // trigram
  connector: "\u2194",   // left-right arrow
  group:     "\u25A1",   // white square
};

interface Props {
  roomId: string;
  nodes: CanvasNode[];
  artifacts: Artifact[];
  token: string;
  readOnly?: boolean;
  onNodesChanged: () => void;
}

export function RoomCanvas({ roomId, nodes, artifacts, token, readOnly, onNodesChanged }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Build a lookup from artifact_id → Artifact
  const artifactMap = useRef(new Map<string, Artifact>());
  useEffect(() => {
    const m = new Map<string, Artifact>();
    artifacts.forEach((a) => m.set(a.artifact_id, a));
    artifactMap.current = m;
  }, [artifacts]);

  // Responsive sizing
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(([entry]) => {
      setDimensions({
        width: Math.floor(entry.contentRect.width),
        height: Math.floor(entry.contentRect.height),
      });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // ── D3 render ────────────────────────────────────────────────────────────
  useEffect(() => {
    const svg = d3.select(svgRef.current);
    if (!svg.node()) return;

    svg.selectAll("*").remove();

    const { width, height } = dimensions;

    // Background grid pattern
    const defs = svg.append("defs");
    defs.append("pattern")
      .attr("id", "grid")
      .attr("width", 24).attr("height", 24)
      .attr("patternUnits", "userSpaceOnUse")
      .append("path")
      .attr("d", "M 24 0 L 0 0 0 24")
      .attr("fill", "none")
      .attr("stroke", "#1e293b")
      .attr("stroke-width", 0.5);

    // Root group for zoom/pan
    const g = svg.append("g");

    // Grid background
    g.append("rect")
      .attr("width", width * 4)
      .attr("height", height * 4)
      .attr("x", -width * 2)
      .attr("y", -height * 2)
      .attr("fill", "url(#grid)")
      .style("pointer-events", "none");

    // Zoom behaviour
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });
    svg.call(zoom);

    // ── Draw nodes ────────────────────────────────────────────────────────
    const nodeGroups = g.selectAll<SVGGElement, CanvasNode>(".canvas-node")
      .data(nodes, (d) => d.node_id)
      .join("g")
      .attr("class", "canvas-node")
      .attr("transform", (d) => `translate(${d.x}, ${d.y})`);

    // Node background rect
    nodeGroups.append("rect")
      .attr("width", (d) => d.width)
      .attr("height", (d) => d.height)
      .attr("rx", 8)
      .attr("ry", 8)
      .attr("fill", (d) => {
        if (d.artifact_id) {
          const art = artifactMap.current.get(d.artifact_id);
          return art ? ARTIFACT_COLORS[art.artifact_type]?.bg ?? "#1e293b" : "#1e293b";
        }
        return "#1e293b";
      })
      .attr("stroke", (d) => {
        if (d.artifact_id) {
          const art = artifactMap.current.get(d.artifact_id);
          return art ? ARTIFACT_COLORS[art.artifact_type]?.border ?? "#334155" : "#334155";
        }
        return "#334155";
      })
      .attr("stroke-width", 1.5)
      .style("filter", "drop-shadow(0 2px 4px rgba(0,0,0,0.3))");

    // Type icon (top-left badge)
    nodeGroups.append("text")
      .attr("x", 10)
      .attr("y", 20)
      .attr("font-size", "12px")
      .attr("fill", "#64748b")
      .text((d) => {
        if (d.artifact_id) {
          const art = artifactMap.current.get(d.artifact_id);
          return art ? art.artifact_type.slice(0, 4) : NODE_TYPE_ICONS[d.node_type] ?? "";
        }
        return NODE_TYPE_ICONS[d.node_type] ?? "";
      });

    // Title text
    nodeGroups.append("text")
      .attr("x", 10)
      .attr("y", 40)
      .attr("font-size", "13px")
      .attr("font-weight", 600)
      .attr("fill", (d) => {
        if (d.artifact_id) {
          const art = artifactMap.current.get(d.artifact_id);
          return art ? ARTIFACT_COLORS[art.artifact_type]?.text ?? "#e2e8f0" : "#e2e8f0";
        }
        return "#e2e8f0";
      })
      .text((d) => {
        if (d.artifact_id) {
          const art = artifactMap.current.get(d.artifact_id);
          return art ? truncate(art.title || "Untitled", 22) : d.label || "Node";
        }
        return truncate(d.label || "Node", 22);
      });

    // Author / subtitle
    nodeGroups.append("text")
      .attr("x", 10)
      .attr("y", 58)
      .attr("font-size", "10px")
      .attr("fill", "#64748b")
      .text((d) => {
        if (d.artifact_id) {
          const art = artifactMap.current.get(d.artifact_id);
          return art ? `by ${truncateDid(art.author_did)}` : `by ${truncateDid(d.created_by)}`;
        }
        return truncateDid(d.created_by);
      });

    // ── Drag behaviour ──────────────────────────────────────────────────
    if (!readOnly) {
      const drag = d3.drag<SVGGElement, CanvasNode>()
        .on("start", function () {
          d3.select(this).raise();
          d3.select(this).select("rect").attr("stroke-width", 2.5);
        })
        .on("drag", function (event, d) {
          d.x = event.x;
          d.y = event.y;
          d3.select(this).attr("transform", `translate(${d.x}, ${d.y})`);
        })
        .on("end", function (_event, d) {
          d3.select(this).select("rect").attr("stroke-width", 1.5);
          // Persist position to backend
          updateCanvasNode(roomId, d.node_id, { x: d.x, y: d.y }, token)
            .then(() => onNodesChanged())
            .catch(() => {});
        });

      nodeGroups.call(drag);
      nodeGroups.style("cursor", "grab");
    }

    // ── Empty state ─────────────────────────────────────────────────────
    if (nodes.length === 0) {
      g.append("text")
        .attr("x", width / 2)
        .attr("y", height / 2)
        .attr("text-anchor", "middle")
        .attr("font-size", "14px")
        .attr("fill", "#475569")
        .text("Drop artifacts here to build your shared canvas");

      g.append("text")
        .attr("x", width / 2)
        .attr("y", height / 2 + 24)
        .attr("text-anchor", "middle")
        .attr("font-size", "11px")
        .attr("fill", "#334155")
        .text("Use the sidebar to add notes, code, diagrams, and more");
    }

  }, [nodes, artifacts, dimensions, readOnly, roomId, token, onNodesChanged]);

  return (
    <div ref={containerRef} className="w-full h-full bg-slate-950 overflow-hidden relative">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="block"
      />
      {/* Zoom hint */}
      <div className="absolute bottom-3 left-3 text-[10px] text-slate-600 select-none">
        Scroll to zoom &middot; Drag to pan &middot; Drag nodes to reposition
      </div>
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "\u2026" : s;
}

function truncateDid(did: string): string {
  if (!did) return "";
  // "did:agentx:atlas-001" → "atlas-001"
  const parts = did.split(":");
  return parts[parts.length - 1] ?? did;
}
