"use client";
import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { agentXWs, type WsMessage } from "@/lib/websocket";

type Node = { id: string; trust: number };
type Link = { source: string; target: string };
type SimNode = Node & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode>;

function trustColor(trust: number): string {
  if (trust > 0.8) return "#22c55e"; // green
  if (trust > 0.5) return "#eab308"; // yellow
  return "#ef4444";                  // red
}

export function AgentNetworkGraph({
  nodes,
  links,
}: {
  nodes: Node[];
  links: Link[];
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    // Clear previous render (strict-mode / hot-reload safe)
    d3.select(ref.current).selectAll("*").remove();

    const width = ref.current.offsetWidth || 900;
    const height = 600;

    // ── SVG ─────────────────────────────────────────────────────────────────
    const svg = d3
      .select(ref.current)
      .append("svg")
      .attr("width", "100%")
      .attr("height", height)
      .attr("viewBox", `0 0 ${width} ${height}`)
      .style("overflow", "hidden")
      .style("cursor", "grab");

    // Single zoom-root group — zoom/pan transforms this
    const zoomRoot = svg.append("g").attr("class", "zoom-root");

    // ── Zoom / pan ───────────────────────────────────────────────────────────
    svg.call(
      d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 8])
        .on("zoom", (event) => {
          zoomRoot.attr("transform", event.transform);
          svg.style("cursor", event.transform.k > 1 ? "grabbing" : "grab");
        })
    );

    // ── Tooltip (scoped to container, not body) ──────────────────────────────
    const tooltip = d3
      .select(ref.current)
      .append("div")
      .style("position", "absolute")
      .style("background", "#1e293b")
      .style("color", "#f1f5f9")
      .style("padding", "5px 10px")
      .style("border-radius", "6px")
      .style("font-size", "11px")
      .style("font-family", "monospace")
      .style("pointer-events", "none")
      .style("box-shadow", "0 2px 8px rgba(0,0,0,.5)")
      .style("opacity", 0)
      .style("z-index", "10")
      .style("max-width", "260px")
      .style("word-break", "break-all");

    // ── Simulation data (mutable — WS handler mutates these) ─────────────────
    const nodeData: SimNode[] = nodes.map((n) => ({ ...n }));
    const linkData: SimLink[] = links.map((l) => ({ ...l }));

    // Track node IDs for duplicate-free WS insertions
    const nodeIds = new Set<string>(nodeData.map((n) => n.id));

    // ── Force simulation ─────────────────────────────────────────────────────
    const linkForce = d3
      .forceLink<SimNode, SimLink>(linkData)
      .id((d) => d.id)
      .distance(120);

    const simulation = d3
      .forceSimulation(nodeData)
      .force("link", linkForce)
      .force("charge", d3.forceManyBody().strength(-220))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<SimNode>().radius((d) => 6 + d.trust * 8));

    // ── Link group ───────────────────────────────────────────────────────────
    const linkGroup = zoomRoot
      .append("g")
      .attr("stroke-opacity", 0.5)
      .attr("stroke-width", 1);

    let linkSel = linkGroup
      .selectAll<SVGLineElement, SimLink>("line")
      .data(linkData)
      .join("line")
      .attr("stroke", "#334155");

    // ── Node group ───────────────────────────────────────────────────────────
    const nodeGroup = zoomRoot.append("g");

    const node = nodeGroup
      .selectAll<SVGCircleElement, SimNode>("circle")
      .data(nodeData)
      .join("circle")
      .attr("r", (d) => 4 + d.trust * 8)
      .attr("fill", (d) => trustColor(d.trust))
      .attr("fill-opacity", 0.85)
      .attr("stroke", "#1e293b")
      .attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .call(
        d3
          .drag<SVGCircleElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      )
      // Tooltip
      .on("mouseover", (_event, d) => {
        tooltip.style("opacity", 1).html(
          `<strong>${d.id.slice(0, 32)}${d.id.length > 32 ? "…" : ""}</strong>` +
          `<br/>trust: ${(d.trust * 100).toFixed(0)}%`
        );
      })
      .on("mousemove", (event: MouseEvent) => {
        // offsetX/offsetY are relative to the container div — correct for abs tooltip
        tooltip
          .style("left", event.offsetX + 14 + "px")
          .style("top", event.offsetY - 10 + "px");
      })
      .on("mouseout", () => tooltip.style("opacity", 0))
      // Click → agent profile
      .on("click", (_event, d) => {
        window.location.href = `/agents/${encodeURIComponent(d.id)}`;
      });

    // ── Tick ─────────────────────────────────────────────────────────────────
    simulation.on("tick", () => {
      linkSel
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);

      node.attr("cx", (d: any) => d.x).attr("cy", (d: any) => d.y);
    });

    // ── WebSocket — live edge insertions ─────────────────────────────────────
    const wsHandler = (msg: WsMessage) => {
      if (msg.type !== "TRUST_UPDATE") return;
      const { source, target } = msg.data as { source: string; target: string };

      // Duplicate-edge protection
      if (
        linkData.some(
          (l: any) => l.source === source && l.target === target
        )
      )
        return;

      // Missing-node protection
      if (!nodeIds.has(source)) {
        nodeData.push({ id: source, trust: 0.5 });
        nodeIds.add(source);
      }
      if (!nodeIds.has(target)) {
        nodeData.push({ id: target, trust: 0.5 });
        nodeIds.add(target);
      }

      linkData.push({ source, target } as SimLink);

      // Re-join link selection with updated data
      linkSel = linkGroup
        .selectAll<SVGLineElement, SimLink>("line")
        .data(linkData)
        .join("line")
        .attr("stroke", "#334155");

      // Update force and restart
      linkForce.links(linkData);
      simulation.nodes(nodeData);
      simulation.alpha(0.5).restart();
    };

    agentXWs.onMessage(wsHandler);

    // Connect WS only in the browser, and only when a token is stored
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("agentx_token");
      if (token) {
        agentXWs.connect(token);
        agentXWs.subscribe("feed");
        agentXWs.subscribe("alerts");
      }
    }

    // ── Cleanup ───────────────────────────────────────────────────────────────
    return () => {
      simulation.stop();
      agentXWs.offMessage(wsHandler);
    };
  }, [nodes, links]);

  // position: relative scopes the absolute-positioned tooltip to this container
  return <div ref={ref} className="w-full h-[600px] relative" />;
}
