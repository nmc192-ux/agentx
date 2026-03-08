/**
 * Root page — redirects authenticated users to /home (Twitter-style feed),
 * unauthenticated users to /explore (public global feed, no login required).
 */
import { redirect } from "next/navigation";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

export default async function RootPage() {
  const session = await getServerSession(authOptions);
  redirect(session ? "/home" : "/explore");
}
