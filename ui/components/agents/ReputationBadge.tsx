export function ReputationBadge({ score }: { score: number }) {
  const pct = Math.round((score ?? 0) * 100);
  const color =
    pct >= 80
      ? "text-green-500"
      : pct >= 50
      ? "text-yellow-500"
      : "text-red-500";
  return (
    <span className={`text-xs font-bold font-mono ${color}`}>{pct}%</span>
  );
}
