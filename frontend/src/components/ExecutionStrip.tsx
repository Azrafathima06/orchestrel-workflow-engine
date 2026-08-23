import { useMemo } from "react";
import type { TaskRunSummary } from "@/api/types";
import { statusMeta } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * Order tasks by real start time for the strip's left-to-right reading —
 * tasks that haven't started yet sort last, ties broken by task_key for a
 * stable render. This is a fingerprint of *when things started*, not a
 * claim about concurrency: two tasks that ran in parallel still get two
 * distinct positions, exactly as a DAG's execution log would list them.
 */
export function orderTasksForStrip(tasks: TaskRunSummary[]): TaskRunSummary[] {
  return [...tasks].sort((a, b) => {
    const at = a.started_at ? new Date(a.started_at).getTime() : Number.POSITIVE_INFINITY;
    const bt = b.started_at ? new Date(b.started_at).getTime() : Number.POSITIVE_INFINITY;
    if (at !== bt) return at - bt;
    return a.task_key.localeCompare(b.task_key);
  });
}

interface ExecutionStripProps {
  tasks: TaskRunSummary[];
  className?: string;
}

/**
 * Orchestrel's signature visual: a quick fingerprint of one run's execution,
 * distinct from the DAG. Every mark comes from a real task_run — its
 * status decides shape and fill, so a viewer can tell "ran and failed"
 * (filled diamond) from "never ran" (hollow, dashed) without reading a
 * single label. Not a replacement for the graph; a run can be recognised
 * from this strip alone the way a waveform identifies a sound.
 */
export function ExecutionStrip({ tasks, className }: ExecutionStripProps) {
  const ordered = useMemo(() => orderTasksForStrip(tasks), [tasks]);

  if (ordered.length === 0) return null;

  return (
    <div className={cn("relative flex h-3.5 items-center", className)}>
      <div className="absolute inset-x-0 h-px bg-[var(--color-border)]" />
      <div className="relative flex w-full items-center justify-between">
        {ordered.map((task) => (
          <StripMark key={task.id} task={task} />
        ))}
      </div>
    </div>
  );
}

function StripMark({ task }: { task: TaskRunSummary }) {
  const meta = statusMeta(task.status);
  const color = `var(${meta.cssVar})`;

  const shapeClass =
    task.status === "failed"
      ? "rotate-45 rounded-[1.5px]" // diamond — distinct silhouette from a plain circle
      : "rounded-full";

  return (
    <span
      role="img"
      aria-label={`${task.task_key}: ${meta.label}`}
      title={`${task.task_key} · ${meta.label}`}
      className={cn(
        "relative z-10 block h-[7px] w-[7px] shrink-0 bg-[var(--color-surface-1)]",
        shapeClass,
        !meta.hasExecuted && "border border-dashed",
        task.status === "retrying" && "ring-1 ring-offset-1 ring-offset-[var(--color-surface-1)]",
      )}
      style={{
        backgroundColor: meta.hasExecuted ? color : "transparent",
        borderColor: !meta.hasExecuted ? color : undefined,
        ...(task.status === "retrying" ? { ["--tw-ring-color" as string]: color } : {}),
      }}
    />
  );
}
