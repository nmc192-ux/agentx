import { TwitterShell } from "@/components/TwitterShell";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <TwitterShell>{children}</TwitterShell>;
}
