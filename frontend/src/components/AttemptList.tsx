import { ChevronDown, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { AttemptDetail } from "@/api/types";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";
import { StatusPill } from "./StatusPill";

function AttemptRow({ attempt }: { attempt: AttemptDetail }) {
  const [expanded, setExpanded] = useState(false);
  const isWorkerLost = attempt.error_type === "WorkerLost";

  return (
    <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface-1)]">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-[var(--color-text-tertiary)]">
            #{attempt.attempt_number}
          </span>
          <StatusPill status={attempt.status} size="sm" />
          {isWorkerLost && (
            <span className="flex items-center gap-1 text-[11px] text-[var(--color-status-retrying)]">
              <ShieldAlert className="h-3 w-3" />
              Worker lost — attempt reclaimed
            </span>
          )}
        </div>
        <span className="font-mono text-[11px] tabular-nums text-[var(--color-text-tertiary)]">
          {formatDuration(attempt.duration_ms)}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--color-border-subtle)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        <span className="font-mono">{attempt.worker_id}</span>
        <span>{formatTimestamp(attempt.started_at)}</span>
      </div>

      {attempt.error_type && !isWorkerLost && (
        <div className="border-t border-[var(--color-border-subtle)] px-3 py-2">
          <p className="text-xs text-[var(--color-status-failed)]">
            <span className="font-mono font-medium">{attempt.error_type}</span>
            {attempt.error_message && `: ${attempt.error_message}`}
          </p>
          {attempt.traceback && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="mt-1.5 flex items-center gap-1 text-[11px] text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
            >
              <ChevronDown className={cn("h-3 w-3 transition-transform", expanded && "rotate-180")} />
              {expanded ? "Hide" : "Show"} traceback
            </button>
          )}
          {expanded && attempt.traceback && (
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-[var(--color-surface-0)] p-2.5 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
              {attempt.traceback}
            </pre>
          )}
        </div>
      )}
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
    <div className="space-y-1.5">
      {attempts.map((a) => (
        <AttemptRow key={a.attempt_number} attempt={a} />
      ))}
    </div>
  );
}
