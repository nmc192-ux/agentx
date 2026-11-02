/**
 * AgentX — /profile/[did]: historical alias. Goes to /agents/[did], which
 * sends the visitor on to /@handle (S2-9b).
 */
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ did: string }> }

export default async function ProfileAlias({ params }: Props) {
  const { did } = await params;
  redirect(`/agents/${encodeURIComponent(decodeURIComponent(did))}`);
}
