import { AlertCircle } from "lucide-react";
import { Button } from "./Button";

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

/** Human-readable error + retry action. Never surfaces a raw stack trace or fetch error. */
export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--color-status-failed)]/25 bg-[var(--color-status-failed)]/10">
        <AlertCircle className="h-5 w-5 text-[var(--color-status-failed)]" strokeWidth={1.75} />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-[var(--color-text-primary)]">
          Something went wrong
        </p>
        <p className="max-w-sm text-sm text-[var(--color-text-tertiary)]">
          {message ?? "Couldn't load this data. Please try again."}
        </p>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
