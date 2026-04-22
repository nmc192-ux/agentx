"use client";

/**
 * AgentX — Constellation Graph
 * Phase 1 Enhanced Social Layer: Interactive D3 force graph with relationship filters.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { Filter, Loader2, ZoomIn, ZoomOut } from "lucide-react";
import * as d3 from "d3";
import { getConstellation } from "@/lib/api";
import type { ConstellationGraph as CGraph, ConstellationNode, ConstellationEdge } from "@/types";

const EDGE_COLORS: Record<string, string> = {
  follows:          "#3B82F6",
  followed_by:      "#60A5FA",
  shared_community: "#22C55E",
  collaborator:     "#F59E0B",
};

interface Props {
  centerDid?: string;
  width?:     number;
  height?:    number;
}

export function ConstellationGraph({ centerDid, width = 700, height = 500 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [graph, setGraph] = useState<CGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [hops, setHops] = useState(2);
  const [minTrust, setMinTrust] = useState(0);

  const fetchGraph = useCallback(async () => {
    if (!centerDid) return;
    setLoading(true);
    try {
      const data = await getConstellation(centerDid, { hops, min_trust: minTrust });
      setGraph(data);
    } finally {
      setLoading(false);
    }
  }, [centerDid, hops, minTrust]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  useEffect(() => {
    if (!graph || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const g = svg.append("g");

    // Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on("zoom", (e) => g.attr("transform", e.transform));
    svg.call(zoom);

    const nodes = graph.nodes.map((n) => ({ ...n }));
    const links = graph.edges.map((e) => ({ ...e }));

    const simulation = d3.forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force("link", d3.forceLink(links as d3.SimulationLinkDatum<d3.SimulationNodeDatum>[])
        .id((d: any) => d.did)
        .distance(80))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(25));

    // Edges
    const link = g.append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d: any) => EDGE_COLORS[d.type] ?? "#475569")
      .attr("stroke-opacity", 0.4)
      .attr("stroke-width", 1.5);

    // Nodes
    const node = g.append("g")
      .selectAll<SVGGElement, (typeof nodes)[0]>("g")
      .data(nodes)
      .join("g")
      .call(d3.drag<SVGGElement, any>()
        .on("start", (e, d: any) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (e, d: any) => { d.fx = e.x; d.fy = e.y; })
        .on("end", (e, d: any) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    node.append("circle")
      .attr("r", (d: any) => d.did === centerDid ? 14 : 8 + d.trust * 6)
      .attr("fill", (d: any) => {
        if (d.did === centerDid) return "#06b6d4";
        if (d.trust >= 0.9) return "#F59E0B";
        if (d.trust >= 0.7) return "#8B5CF6";
        return "#3B82F6";
      })
      .attr("stroke", "#1e293b")
      .attr("stroke-width", 2)
      .style("cursor", "pointer");

    node.append("text")
      .text((d: any) => d.name || d.did.split(":").pop())
      .attr("dy", (d: any) => (d.did === centerDid ? 24 : 18))
      .attr("text-anchor", "middle")
      .attr("fill", "#94a3b8")
      .attr("font-size", "10px");

    // Tooltip on hover
    node.append("title")
      .text((d: any) => `${d.name}\nTrust: ${(d.trust * 100).toFixed(0)}%\nTier: ${d.tier}`);

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => { simulation.stop(); };
  }, [graph, centerDid, width, height]);

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex items-center gap-4 text-sm">
        <Filter className="w-4 h-4 text-slate-500" />
        <label className="flex items-center gap-1.5 text-slate-400">
          Hops:
          <select
            value={hops}
            onChange={(e) => setHops(Number(e.target.value))}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-xs"
          >
            {[1, 2, 3, 4].map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-slate-400">
          Min Trust:
          <input
            type="range"
            min={0}
            max={100}
            value={minTrust * 100}
            onChange={(e) => setMinTrust(Number(e.target.value) / 100)}
            className="w-20 accent-cyan-500"
          />
          <span className="text-xs w-8">{(minTrust * 100).toFixed(0)}%</span>
        </label>
        {loading && <Loader2 className="w-4 h-4 text-cyan-400 animate-spin ml-auto" />}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 text-[10px] text-slate-500">
        {Object.entries(EDGE_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-3 h-0.5 rounded" style={{ backgroundColor: color }} />
            {type.replace("_", " ")}
          </span>
        ))}
      </div>

      {/* Graph */}
      <div className="rounded-xl border border-slate-800 bg-slate-950 overflow-hidden">
        {!graph || graph.nodes.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
            {loading ? "Loading graph…" : "Select an agent to explore the constellation"}
          </div>
        ) : (
          <svg ref={svgRef} width={width} height={height} className="w-full" />
        )}
      </div>
    </div>
  );
}
