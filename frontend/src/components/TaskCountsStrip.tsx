import type { TaskCounts } from "@/api/types";
import { statusMeta } from "@/lib/status";
import { cn } from "@/lib/utils";

// Succeeded first (draws the eye to "how much is done"), then in-flight
// states, then not-yet-started, then the states that mean nothing more
// will happen.
const SEGMENT_ORDER: (keyof TaskCounts)[] = [
  "succeeded",
  "running",
  "retrying",
  "queued",
  "pending",
  "upstream_failed",
  "failed",
  "cancelled",
];

/**
 * A list-row sibling of ExecutionStrip: run list rows only carry aggregate
 * task_counts, not individual task_run records, so this renders proportional
 * segments by count rather than one mark per task. Same real data, coarser
 * grain — still never fabricated.
 */
export function TaskCountsStrip({ counts, className }: { counts: TaskCounts; className?: string }) {
  if (counts.total === 0) return null;

  const segments = SEGMENT_ORDER.filter((key) => counts[key] > 0);

  return (
    <div
      className={cn("flex h-[5px] w-full overflow-hidden rounded-[2px] bg-[var(--color-surface-2)]", className)}
      role="img"
      aria-label={`${counts.succeeded} of ${counts.total} tasks succeeded`}
    >
      {segments.map((key) => {
        const meta = statusMeta(key);
        const pct = (counts[key] / counts.total) * 100;
        return (
          <div
            key={key}
            title={`${key.replace("_", " ")}: ${counts[key]}`}
            style={{ width: `${pct}%`, backgroundColor: `var(${meta.cssVar})` }}
          />
        );
      })}
    </div>
  );
}
