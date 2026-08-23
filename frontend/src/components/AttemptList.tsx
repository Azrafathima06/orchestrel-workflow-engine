import { ChevronDown, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { AttemptDetail } from "@/api/types";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { statusMeta } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * Compact event-timeline row, not a card: attempt number, status, worker,
 * duration on one monospace line — reads like a log line, which is the
 * mental model this is standing in for.
 *
 *   01  FAILED   worker-abc-1  4ms
 *       RetriableError: connection reset
 */
function AttemptRow({ attempt }: { attempt: AttemptDetail }) {
  const [expanded, setExpanded] = useState(false);
  const isWorkerLost = attempt.error_type === "WorkerLost";
  const meta = statusMeta(attempt.status);

  return (
    <div className="py-1.5 font-mono text-xs">
      <div className="flex items-center gap-2.5">
        <span className="w-4 shrink-0 text-[var(--color-text-tertiary)]">
          {String(attempt.attempt_number).padStart(2, "0")}
        </span>
        <span className={cn("w-16 shrink-0 uppercase tracking-tight", meta.textClass)}>
          {attempt.status}
        </span>
        <span className="min-w-0 flex-1 truncate text-[var(--color-text-secondary)]">
          {attempt.worker_id}
        </span>
        <span className="shrink-0 tabular-nums text-[var(--color-text-tertiary)]">
          {formatDuration(attempt.duration_ms)}
        </span>
      </div>

      {isWorkerLost && (
        <p className="mt-0.5 flex items-center gap-1 pl-[26px] text-[11px] text-[var(--color-status-retrying)]">
          <ShieldAlert className="h-3 w-3" />
          Worker lost — attempt reclaimed
        </p>
      )}

      {attempt.error_type && !isWorkerLost && (
        <div className="mt-0.5 pl-[26px] text-[11px] text-[var(--color-status-failed)]">
          <span className="font-medium">{attempt.error_type}</span>
          {attempt.error_message && `: ${attempt.error_message}`}
          {attempt.traceback && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="ml-2 inline-flex items-center gap-0.5 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
            >
              <ChevronDown className={cn("h-2.5 w-2.5 transition-transform", expanded && "rotate-180")} />
              {expanded ? "hide" : "traceback"}
            </button>
          )}
          {expanded && attempt.traceback && (
            <pre className="mt-1.5 max-h-48 overflow-auto rounded-[var(--radius-sm)] bg-[var(--color-surface-0)] p-2.5 text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
              {attempt.traceback}
            </pre>
          )}
        </div>
      )}

      <p className="mt-0.5 pl-[26px] text-[11px] text-[var(--color-text-tertiary)]">
        {formatTimestamp(attempt.started_at)}
      </p>
    </div>
  );
}

export function AttemptList({ attempts }: { attempts: AttemptDetail[] }) {
  if (attempts.length === 0) {
    return (
      <p className="text-xs text-[var(--color-text-tertiary)]">
        No attempts yet — this task has not started.
      </p>
    );
  }

  return (
    <div className="divide-y divide-[var(--color-border-subtle)]">
      {attempts.map((a) => (
        <AttemptRow key={a.attempt_number} attempt={a} />
      ))}
    </div>
  );
}
