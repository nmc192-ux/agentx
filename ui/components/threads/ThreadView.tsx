import { CommentTree } from "./CommentTree";

type Comment = {
  comment_id: string;
  author_did: string;
  content: string;
  depth: number;
  created_at: string;
};

export function ThreadView({
  thread,
  comments,
}: {
  thread: Record<string, unknown>;
  comments: Comment[];
}) {
  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-bold mb-1">{thread.title as string}</h2>
      <p className="text-xs text-slate-500 mb-4">
        {thread.comment_count as number} comments
      </p>
      <CommentTree comments={comments} />
    </div>
  );
}
