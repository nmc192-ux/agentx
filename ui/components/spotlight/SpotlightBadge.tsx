import { FEATURE_SPOTLIGHT } from "@/lib/flags";
import { getSpotlight } from "@/lib/api";

/** "Agent of the week" badge for a profile. Server component: renders only
 *  when this agent is this week's pick; any failure hides it. */
export async function SpotlightBadge({ did }: { did: string }) {
  if (!FEATURE_SPOTLIGHT) return null;
  const pick = await getSpotlight().catch(() => null);
  if (!pick?.agent || pick.agent.agent_did !== did) return null;
  return (
    <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-500 font-medium">
      ★ Agent of the week
    </span>
  );
}
