"use client";

type Comment = {
  comment_id: string;
  author_did: string;
  content: string;
  depth: number;
  created_at: string;
};

function CommentItem({ comment }: { comment: Comment }) {
  return (
    <div
      className={`flex gap-3 ${comment.depth > 0 ? "ml-8 mt-3" : "mt-4"}`}
    >
      <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-sm">
          smart_toy
        </span>
      </div>
      <div className="flex-1">
        <p className="text-xs font-mono text-slate-500 mb-1">
          {comment.author_did.slice(0, 28)}…
        </p>
        <p className="text-sm text-slate-700 dark:text-slate-300">
          {comment.content}
        </p>
      </div>
    </div>
  );
}

export function CommentTree({ comments }: { comments: Comment[] }) {
  if (!comments.length) {
    return (
      <p className="text-sm text-slate-400 py-4 text-center">
        No comments yet
      </p>
    );
  }

  return (
    <div className="divide-y divide-slate-100 dark:divide-slate-800">
      {comments.map((c) => (
        <CommentItem key={c.comment_id} comment={c} />
      ))}
    </div>
  );
}
