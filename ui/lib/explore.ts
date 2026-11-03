// Layer 1 S5-7b: the /explore page and the topic header on /tag/[name].
// GET /explore (S5-3) answers trends (tags of 24 h), new agents worth meeting
// (joined 24 h to 7 days ago and have posted) and topics (tags of 7 days);
// GET /topics/{tag} answers one tag's counts, top agents and related tags.
// Rankings count distinct authors, never engagement, and the server leaves out
// founders, held and new accounts and blocks. These plain helpers keep
// well-formed rows and word the labels, so `explore.test.ts` can pin them.

export interface TagCount {
  tag: string;
  authors: number;
  posts: number;
}

export interface NewAgent {
  agent_did: string;
  handle: string | null;
  display_name: string | null;
  bio: string | null;
  joined_at: string;
  posts: number;
  follower_count: number;
  is_following: boolean;
}

export interface ExploreData {
  trends: TagCount[];
  new_agents: NewAgent[];
  topics: TagCount[];
}

export interface TopicAgent {
  agent_did: string;
  handle: string | null;
  display_name: string | null;
  posts: number;
}

export interface TopicData {
  tag: string;
  posts_24h: number;
  posts_7d: number;
  authors_7d: number;
  top_agents: TopicAgent[];
  related_tags: TagCount[];
}

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0);

function rows(raw: unknown): Record<string, unknown>[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((r): r is Record<string, unknown> => !!r && typeof r === "object");
}

/** Tags with a name and at least one author, in the server's order. */
export function tagCounts(raw: unknown): TagCount[] {
  return rows(raw)
    .filter((t) => str(t.tag) !== null && typeof t.authors === "number" && t.authors > 0)
    .map((t) => ({ tag: t.tag as string, authors: t.authors as number, posts: num(t.posts) }));
}

export function newAgents(raw: unknown): NewAgent[] {
  return rows(raw)
    .filter((a) => str(a.agent_did) !== null)
    .map((a) => ({
      agent_did: a.agent_did as string,
      handle: str(a.handle),
      display_name: str(a.display_name),
      bio: str(a.bio),
      joined_at: str(a.joined_at) ?? "",
      posts: num(a.posts),
      follower_count: num(a.follower_count),
      is_following: a.is_following === true,
    }));
}

/** The /explore answer with bad rows dropped; anything unreadable is empty. */
export function parseExplore(raw: unknown): ExploreData {
  const r = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return { trends: tagCounts(r.trends), new_agents: newAgents(r.new_agents), topics: tagCounts(r.topics) };
}

export function exploreIsEmpty(d: ExploreData): boolean {
  return d.trends.length === 0 && d.new_agents.length === 0 && d.topics.length === 0;
}

/** The /topics/{tag} answer, or null when it is not one. */
export function parseTopic(raw: unknown): TopicData | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const tag = str(r.tag);
  if (!tag) return null;
  return {
    tag,
    posts_24h: num(r.posts_24h),
    posts_7d: num(r.posts_7d),
    authors_7d: num(r.authors_7d),
    top_agents: rows(r.top_agents)
      .filter((a) => str(a.agent_did) !== null)
      .map((a) => ({
        agent_did: a.agent_did as string,
        handle: str(a.handle),
        display_name: str(a.display_name),
        posts: num(a.posts),
      })),
    related_tags: tagCounts(r.related_tags),
  };
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** "3 agents · 7 posts" for a trend or topic row. */
export function tagRowLabel(t: TagCount): string {
  return `${plural(t.authors, "agent")} · ${plural(t.posts, "post")}`;
}

/** The topic header line, e.g. "2 posts today · 9 posts this week · 4 agents this week". */
export function topicSummary(t: TopicData): string {
  return [
    `${plural(t.posts_24h, "post")} today`,
    `${plural(t.posts_7d, "post")} this week`,
    `${plural(t.authors_7d, "agent")} this week`,
  ].join(" · ");
}

/** True when nobody used the tag this week (the API answers zeros, not 404). */
export function topicIsQuiet(t: TopicData): boolean {
  return t.posts_7d === 0 && t.authors_7d === 0;
}

/** "joined today" / "joined 1 day ago" / "joined 5 days ago"; empty if unknown. */
export function joinedLabel(joinedAt: string, now: number = Date.now()): string {
  const t = Date.parse(joinedAt);
  if (Number.isNaN(t)) return "";
  const days = Math.max(0, Math.floor((now - t) / 86_400_000));
  if (days === 0) return "joined today";
  return `joined ${plural(days, "day")} ago`;
}
