"use client";
import { useEffect, useRef } from "react";

type Node = {
  agent_did: string;
  trust_score: number;
  display_name?: string;
};

export function CivilizationMap({ nodes }: { nodes: Node[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;

    // Render up to 200 nodes (zoom/pagination added in Phase 26)
    const placed = nodes.slice(0, 200).map((n) => ({
      x: 80 + Math.random() * (canvas.width - 160),
      y: 80 + Math.random() * (canvas.height - 160),
      r: Math.max(4, 4 + (n.trust_score ?? 0) * 10),
      label: n.display_name ?? n.agent_did.slice(8, 20),
    }));

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    placed.forEach((n) => {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(4, 0, 255, 0.5)";
      ctx.fill();

      ctx.fillStyle = "#e2e8f0";
      ctx.font = "10px Inter, sans-serif";
      ctx.fillText(n.label, n.x + n.r + 3, n.y + 4);
    });
  }, [nodes]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-[500px] bg-background-dark rounded-xl border border-slate-800"
    />
  );
}
