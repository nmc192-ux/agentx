"use client";

import { AlertCircle, RefreshCw } from "lucide-react";

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  message = "Something went wrong",
  onRetry,
  className = "",
}: ErrorStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-16 px-4 text-center ${className}`}>
      <div className="w-12 h-12 rounded-full bg-accent-error/10 flex items-center justify-center mb-4">
        <AlertCircle className="w-6 h-6 text-accent-error" />
      </div>
      <p className="text-text-secondary font-medium mb-1">{message}</p>
      <p className="text-text-quaternary text-sm mb-5">
        Check your connection and try again.
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-surface-secondary border border-border-primary text-text-secondary text-sm hover:text-text-primary hover:bg-surface-tertiary transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Try again
        </button>
      )}
    </div>
  );
}
