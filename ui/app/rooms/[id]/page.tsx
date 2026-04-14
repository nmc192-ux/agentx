"use client";

/**
 * AgentX — Room Detail Page
 * Phase 1 Collaboration Rooms: Canvas + sidebar + real-time activity.
 */
import { useParams } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { RoomView } from "@/components/rooms/RoomView";

export const dynamic = "force-dynamic";

export default function RoomDetailPage() {
  const params = useParams<{ id: string }>();

  return (
    <AppShell>
      <RoomView roomId={params.id} />
    </AppShell>
  );
}
