// Layer 1 (S3-8a): the conversation page as a list of rows, from
// GET /posts/{id}/conversation. A plain function, so `conversation.test.ts`
// pins the layout rules without a browser:
//   • ancestors first (root at the top); one the reader may not see is a
//     "This post is unavailable" row, so the chain still shows its shape;
//   • then the post, then its replies depth-first, oldest first;
//   • a thread (an author replying to their own post as its first reply)
//     stays at the same depth, joined to the post above by a line;
//   • indentation stops at MAX_INDENT so deep trees stay readable;
//   • "more" rows say how many replies are not shown under a post.

export interface ConvPost {
  post_id: string;
  author_did: string;
}

export interface ConvAncestor<P extends ConvPost = ConvPost> {
  post_id: string;
  unavailable?: boolean;
  post?: P | null;
}

export interface ConvNode<P extends ConvPost = ConvPost> {
  post: P;
  replies: ConvNode<P>[];
  more_replies?: number;
}

export interface Conversation<P extends ConvPost = ConvPost> {
  ancestors: ConvAncestor<P>[];
  post: P;
  replies: ConvNode<P>[];
  more_replies?: number;
}

export type ConvRow<P extends ConvPost = ConvPost> =
  | { kind: "ancestor"; key: string; post: P | null }
  | { kind: "focal"; key: string; post: P; joinBelow: boolean }
  | { kind: "reply"; key: string; post: P; depth: number; joinedAbove: boolean; joinBelow: boolean }
  | { kind: "more"; key: string; parentId: string; count: number; depth: number; focal: boolean };

export const MAX_INDENT = 4;

export function conversationRows<P extends ConvPost>(c: Conversation<P>): ConvRow<P>[] {
  const rows: ConvRow<P>[] = [];
  for (const a of c.ancestors ?? []) {
    rows.push({
      kind: "ancestor",
      key: `a:${a.post_id}`,
      post: a.unavailable || !a.post ? null : a.post,
    });
  }
  const focalThread = continuesThread(c.post, c.replies);
  rows.push({ kind: "focal", key: `p:${c.post.post_id}`, post: c.post, joinBelow: focalThread });
  walk(rows, c.post, c.replies, c.more_replies ?? 0, 0, true);
  return rows;
}

/** True when the first reply is by the same author (a thread continues). */
function continuesThread<P extends ConvPost>(parent: P, replies: ConvNode<P>[]): boolean {
  return replies.length > 0 && replies[0].post.author_did === parent.author_did;
}

function walk<P extends ConvPost>(
  rows: ConvRow<P>[], parent: P, replies: ConvNode<P>[], more: number, depth: number, focal: boolean,
): void {
  const threaded = continuesThread(parent, replies);
  replies.forEach((node, i) => {
    const joinedAbove = i === 0 && threaded;
    // A thread continuation stays at the parent's depth; other replies indent.
    const d = Math.min(joinedAbove ? depth : depth + 1, MAX_INDENT);
    rows.push({
      kind: "reply",
      key: `r:${node.post.post_id}`,
      post: node.post,
      depth: d,
      joinedAbove,
      joinBelow: continuesThread(node.post, node.replies),
    });
    walk(rows, node.post, node.replies, node.more_replies ?? 0, d, false);
  });
  if (more > 0) {
    rows.push({
      kind: "more",
      key: `m:${parent.post_id}`,
      parentId: parent.post_id,
      count: more,
      depth: Math.min(depth + 1, MAX_INDENT),
      focal,
    });
  }
}

/** "Show 1 more reply" / "Show 3 more replies". */
export function moreRepliesLabel(count: number): string {
  return `Show ${count} more ${count === 1 ? "reply" : "replies"}`;
}
