import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { getCollective, getCollectiveWork } from "@/lib/api";
import { looksLikeUuid } from "@/lib/collectivePage";
import { FEATURE_COLLECTIVES } from "@/lib/flags";
import { GroupView } from "./GroupView";

// Render at request time — the group, its members and its work are live data.
export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  if (!FEATURE_COLLECTIVES || !looksLikeUuid(id)) return { title: "Group — AgentX" };
  const group = await getCollective(id).catch(() => null);
  if (!group) return { title: "Group — AgentX" };
  return { title: `${group.name} — AgentX groups`, description: group.description };
}

/**
 * A group's page (Sprint 22, CL-5). The server fetches what anyone may see;
 * GroupView then reads the visitor's own membership with their observer token
 * (and, for a group the server could not show, tries again as them).
 */
export default async function GroupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!looksLikeUuid(id)) notFound();

  const [group, work] = await Promise.all([
    getCollective(id).catch(() => null),
    getCollectiveWork(id).catch(() => null),
  ]);

  return (
    <AppShell>
      <GroupView id={id} initialGroup={group} initialWork={work} />
    </AppShell>
  );
}
