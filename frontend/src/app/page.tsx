/**
 * Root page — redirects authenticated users to /dashboard,
 * unauthenticated users to /login.
 */
import { redirect } from "next/navigation";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

export default async function RootPage() {
  const session = await getServerSession(authOptions);
  redirect(session ? "/dashboard" : "/login");
}
