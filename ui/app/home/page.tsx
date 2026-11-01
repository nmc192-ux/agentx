import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/**
 * Duplicate of the home feed at `/` (Layer 1, S1-2b): one feed, one URL.
 * The old page lives in git history if it is ever wanted again.
 */
export default function Page() {
  redirect("/");
}
