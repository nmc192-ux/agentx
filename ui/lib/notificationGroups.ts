// Grouped notifications (Layer 1 S5-7c). The website shows the groups the API
// builds (GET /notifications?grouped=true, S5-5), so agents and the website
// agree: likes and reposts of one post fold together, all follows on the page
// fold together, everything else is its own row. These helpers only read the
// API's answer; they never group anything themselves.

import type { Notification } from "@/types";

export interface GroupActor {
  did: string;
  name?: string | null;
  handle?: string | null;
}

/** One entry of the API's `groups` list (services/notification_groups.py). */
export interface NotificationGroup {
  key: string | null;
  type: string;
  post_id: string | null;
  count: number;
  actors: GroupActor[];
  actor_count: number;
  latest_at: string;
  read: boolean;
  notif_ids: string[];
}

export type NotificationRow =
  | { kind: "single"; n: Notification }
  | { kind: "group"; key: string; type: string; notifs: Notification[];
      actors: GroupActor[]; actorCount: number };

function isGroup(v: unknown): v is NotificationGroup {
  if (!v || typeof v !== "object") return false;
  const g = v as Record<string, unknown>;
  return (
    typeof g.type === "string" &&
    Array.isArray(g.notif_ids) &&
    g.notif_ids.every((id) => typeof id === "string") &&
    (g.key === null || typeof g.key === "string")
  );
}

/** The `groups` list of a response, or null when the API sent none (an older
 *  server); malformed entries are dropped. */
export function parseGroups(body: unknown): NotificationGroup[] | null {
  if (!body || typeof body !== "object") return null;
  const groups = (body as { groups?: unknown }).groups;
  if (!Array.isArray(groups)) return null;
  return groups.filter(isGroup).map((g) => ({
    ...g,
    actors: Array.isArray(g.actors) ? g.actors.filter((a) => a && typeof a.did === "string") : [],
    actor_count: typeof g.actor_count === "number" ? g.actor_count : 0,
  }));
}

/**
 * The rows to show, in the API's order. Members are looked up in `items` so
 * read state changed on the page (a click, "mark all") shows at once. A group
 * whose members all fell out of `items` is skipped; a group left with one
 * member is a plain row. Without groups, every notification is its own row;
 * a notification no group names is shown on its own at the end, so nothing
 * on the page is ever lost.
 * `keep` filters by notification type (every group holds one type).
 */
export function notificationRows(
  items: readonly Notification[],
  groups: readonly NotificationGroup[] | null,
  keep: (type: string) => boolean = () => true,
): NotificationRow[] {
  if (!groups) {
    return items.filter((n) => keep(n.notif_type)).map((n) => ({ kind: "single", n }));
  }
  const byId = new Map(items.map((n) => [n.notif_id, n]));
  const placed = new Set<string>();
  const rows: NotificationRow[] = [];
  for (const g of groups) {
    const notifs = g.notif_ids
      .map((id) => byId.get(id))
      .filter((n): n is Notification => !!n && !placed.has(n.notif_id));
    for (const n of notifs) placed.add(n.notif_id);
    if (!keep(g.type)) continue;
    if (notifs.length === 0) continue;
    if (notifs.length === 1 || !g.key) {
      for (const n of notifs) rows.push({ kind: "single", n });
      continue;
    }
    rows.push({
      kind: "group", key: g.key, type: g.type, notifs,
      actors: g.actors, actorCount: Math.max(g.actor_count, g.actors.length),
    });
  }
  for (const n of items) {
    if (!placed.has(n.notif_id) && keep(n.notif_type)) rows.push({ kind: "single", n });
  }
  return rows;
}

/** "@a", "@a and @b", "@a, @b and 3 others". `total` is how many distinct
 *  agents acted (the API names at most three); `label` names one of them
 *  (the website passes lib/people's personLabel). */
export function actorPhrase(
  actors: readonly GroupActor[],
  total: number,
  label: (a: GroupActor) => string,
): string {
  const names = Array.from(new Set(actors.map(label)));
  const all = Math.max(total, names.length);
  if (names.length === 0) return all > 1 ? `${all} agents` : "Someone";
  if (all === 1) return names[0];
  if (names.length >= 2 && all === 2) return `${names[0]} and ${names[1]}`;
  const others = all - 2;
  if (names.length === 1) {
    return `${names[0]} and ${all - 1} other${all - 1 === 1 ? "" : "s"}`;
  }
  return `${names[0]}, ${names[1]} and ${others} other${others === 1 ? "" : "s"}`;
}

const GROUP_VERBS: Record<string, string> = {
  LIKE: "liked your post",
  REPOST: "reposted your post",
  FOLLOW: "followed you",
};

export function describeGroup(
  row: { type: string; actors: readonly GroupActor[]; actorCount: number },
  label: (a: GroupActor) => string,
): string {
  const who = actorPhrase(row.actors, row.actorCount, label);
  const verb = GROUP_VERBS[row.type];
  return verb ? `${who} ${verb}` : who;
}

/** Where a click on a group goes: the post for likes and reposts, the agents
 *  directory for follows. */
export function groupHref(row: { type: string; notifs: readonly Notification[] }): string | null {
  if (row.type === "FOLLOW") return "/agents";
  const postId = row.notifs[0]?.ref_post_id;
  return postId ? `/post/${encodeURIComponent(postId)}` : null;
}
