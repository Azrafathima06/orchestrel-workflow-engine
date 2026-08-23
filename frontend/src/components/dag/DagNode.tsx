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

export function DagNode({ data }: { data: DagNodeData }) {
  const { task, selected } = data;
  const meta = statusMeta(task.status);
  const Icon = meta.icon;

  const durationLabel =
    task.status === "running"
      ? formatElapsed(task.started_at)
      : task.duration_ms != null
        ? formatDuration(task.duration_ms)
        : null;

  return (
    <div
      className={cn(
        "w-[200px] rounded-lg border bg-[var(--color-surface-1)] px-3 py-2.5 shadow-sm transition-colors",
        selected ? "border-[var(--color-accent)] ring-1 ring-[var(--color-accent)]/40" : meta.borderClass,
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-none !bg-[var(--color-border)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-none !bg-[var(--color-border)]"
      />

      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[13px] font-medium text-[var(--color-text-primary)]">
          {task.task_key}
        </span>
        {task.dispatch_count > 1 && (
          <Tooltip content="Re-dispatched by the recovery sweep after its original broker message became stale or unavailable.">
            <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-[var(--color-status-retrying)]" />
          </Tooltip>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span className={cn("inline-flex items-center gap-1 text-xs font-medium", meta.textClass)}>
          <Icon className={cn("h-3 w-3", meta.spin && "animate-spin")} strokeWidth={2.25} />
          {meta.label}
        </span>
        {durationLabel && (
          <span className="font-mono text-[11px] tabular-nums text-[var(--color-text-tertiary)]">
            {durationLabel}
          </span>
        )}
      </div>

      {task.attempt_count > 1 && (
        <div className="mt-1 text-[11px] tabular-nums text-[var(--color-text-tertiary)]">
          attempt {task.attempt_count}/{task.max_attempts}
        </div>
      )}
    </div>
  );
}
