import { Handle, Position } from "@xyflow/react";
import { ShieldCheck } from "lucide-react";
import { formatDuration, formatElapsed } from "@/lib/format";
import { statusMeta } from "@/lib/status";
import { cn } from "@/lib/utils";
import type { TaskRunSummary } from "@/api/types";
import { Tooltip } from "@/components/ui/Tooltip";

export interface DagNodeData extends Record<string, unknown> {
  task: TaskRunSummary;
  selected: boolean;
}

/**
 * Border treatment per status — dashed vs. solid is load-bearing here, not
 * decorative: it's what makes upstream_failed read as "never ran" at a
 * glance, distinct from failed's solid red border, without opening the
 * inspector. Live states (running/retrying) get a small pulsing dot as
 * the one understated animation on the canvas; everything else is static.
 */
function nodeTreatment(status: string) {
  switch (status) {
    case "succeeded":
      return { border: "border-[var(--color-border)]", dashed: false, pulse: false };
    case "failed":
      return { border: "border-[var(--color-status-failed)]/60", dashed: false, pulse: false };
    case "upstream_failed":
      return {
        border: "border-[var(--color-status-upstream-failed)]/45 border-dashed",
        dashed: true,
        pulse: false,
      };
    case "running":
      return { border: "border-[var(--color-status-running)]/55", dashed: false, pulse: true };
    case "retrying":
      return { border: "border-[var(--color-status-retrying)]/55", dashed: false, pulse: true };
    case "cancelled":
      return { border: "border-[var(--color-border-subtle)] border-dashed", dashed: true, pulse: false };
    default:
      return { border: "border-[var(--color-border-subtle)] border-dashed", dashed: true, pulse: false };
  }
}

export function DagNode({ data }: { data: DagNodeData }) {
  const { task, selected } = data;
  const meta = statusMeta(task.status);
  const Icon = meta.icon;
  const treatment = nodeTreatment(task.status);

  const durationLabel =
    task.status === "running"
      ? formatElapsed(task.started_at)
      : task.duration_ms != null
        ? formatDuration(task.duration_ms)
        : null;

  return (
    <div
      className={cn(
        "w-[168px] rounded-[var(--radius-md)] border bg-[var(--color-surface-1)] px-2.5 py-2 transition-colors",
        selected ? "border-[var(--color-accent)] ring-1 ring-[var(--color-accent)]/40" : treatment.border,
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-none !bg-[var(--color-border)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-none !bg-[var(--color-border)]"
      />

      <div className="flex items-center gap-1.5">
        <span className="relative flex shrink-0 items-center justify-center">
          <Icon className="h-3 w-3" style={{ color: `var(${meta.cssVar})` }} strokeWidth={2.25} />
          {treatment.pulse && (
            <span
              className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 animate-pulse rounded-full"
              style={{ backgroundColor: `var(${meta.cssVar})` }}
            />
          )}
        </span>
        <span className="truncate font-mono text-[12.5px] text-[var(--color-text-primary)]">
          {task.task_key}
        </span>
        {task.dispatch_count > 1 && (
          <Tooltip content="Re-dispatched by the recovery sweep after its original broker message became stale or unavailable.">
            <ShieldCheck className="ml-auto h-3 w-3 shrink-0 text-[var(--color-status-retrying)]" />
          </Tooltip>
        )}
      </div>

      <div className="mt-1 flex items-center justify-between font-mono text-[10.5px] tabular-nums text-[var(--color-text-tertiary)]">
        <span>{durationLabel ?? meta.label}</span>
        {task.attempt_count > 1 && <span>#{task.attempt_count}</span>}
      </div>
    </div>
  );
}
