"use client";
import { useParams } from "next/navigation";
import { DoorOpen } from "lucide-react";
import Link from "next/link";

export default function RoomPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 text-center px-4">
      <div className="w-16 h-16 rounded-2xl bg-accent-primary/10 flex items-center justify-center">
        <DoorOpen size={32} className="text-accent-primary" />
      </div>
      <div>
        <h1 className="text-2xl font-bold text-text-primary mb-2">Room Created</h1>
        <p className="text-text-secondary text-sm mb-1">
          Room ID: <code className="text-accent-primary font-mono">{id}</code>
        </p>
        <p className="text-text-tertiary text-sm">
          Live collaboration rooms are coming soon. Your room has been created successfully.
        </p>
      </div>
      <Link
        href="/feed"
        className="bg-accent-primary text-white px-6 py-2 rounded-full text-sm font-semibold hover:bg-accent-primary/90 transition-colors"
      >
        Back to Feed
      </Link>
    </div>
  );
}
