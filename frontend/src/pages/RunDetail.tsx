import { ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useRun } from "@/api/queries";
import type { TaskRunSummary } from "@/api/types";
import { ExecutionStrip } from "@/components/ExecutionStrip";
import { StatusPill } from "@/components/StatusPill";
import { TaskInspector } from "@/components/TaskInspector";
import { DagLegend } from "@/components/dag/DagLegend";
import { DagView } from "@/components/dag/DagView";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";
import { Tooltip } from "@/components/ui/Tooltip";
import { formatDuration, formatElapsed, formatShortId, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

function RailSegment({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col justify-center px-4 py-2.5 first:pl-0">
      <span className="label-eyebrow">{label}</span>
      <span className="mt-0.5 font-mono text-[15px] font-semibold leading-none tabular-nums text-[var(--color-text-primary)]">
        {value}
      </span>
    </div>
  );
}

function TasksTable({
  tasks,
  selectedTaskKey,
  onSelect,
}: {
  tasks: TaskRunSummary[];
  selectedTaskKey: string | null;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="overflow-x-auto panel">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border-subtle)] text-left">
            <th className="label-eyebrow px-4 py-2 font-medium">Status</th>
            <th className="label-eyebrow px-4 py-2 font-medium">Task</th>
            <th className="label-eyebrow px-4 py-2 font-medium">Attempts</th>
            <th className="label-eyebrow px-4 py-2 font-medium">Worker</th>
            <th className="label-eyebrow px-4 py-2 font-medium">Duration</th>
            <th className="label-eyebrow px-4 py-2 font-medium">Error</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border-subtle)]">
          {tasks.map((t) => (
            <tr
              key={t.id}
              onClick={() => onSelect(t.task_key)}
              className={cn(
                "cursor-pointer",
                selectedTaskKey === t.task_key ? "bg-[var(--color-surface-2)]" : "hover:bg-[var(--color-surface-2)]",
              )}
            >
              <td className="px-4 py-2.5">
                <StatusPill status={t.status} size="sm" />
              </td>
              <td className="px-4 py-2.5 font-mono text-xs text-[var(--color-text-primary)]">
                <span className="inline-flex items-center gap-1.5">
                  {t.task_key}
                  {t.dispatch_count > 1 && (
                    <Tooltip content="Re-dispatched by the recovery sweep.">
                      <ShieldCheck className="h-3 w-3 text-[var(--color-status-retrying)]" />
                    </Tooltip>
                  )}
                </span>
              </td>
              <td className="px-4 py-2.5 text-xs tabular-nums text-[var(--color-text-tertiary)]">
                {t.attempt_count}/{t.max_attempts}
              </td>
              <td className="px-4 py-2.5 truncate font-mono text-xs text-[var(--color-text-tertiary)]">
                {t.worker_id ?? "—"}
              </td>
              <td className="px-4 py-2.5 font-mono text-xs tabular-nums text-[var(--color-text-tertiary)]">
                {formatDuration(t.duration_ms)}
              </td>
              <td className="max-w-48 truncate px-4 py-2.5 text-xs text-[var(--color-status-failed)]">
                {t.error_type ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: run, isLoading, isError, refetch } = useRun(id);
  const [tab, setTab] = useState("graph");
  const [selectedTaskKey, setSelectedTaskKey] = useState<string | null>(null);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);

  const selectedTask = useMemo(
    () => run?.tasks.find((t) => t.task_key === selectedTaskKey) ?? null,
    [run, selectedTaskKey],
  );

  const recoveredCount = useMemo(
    () => run?.tasks.filter((t) => t.dispatch_count > 1).length ?? 0,
    [run],
  );

  const totalAttempts = useMemo(
    () => run?.tasks.reduce((sum, t) => sum + t.attempt_count, 0) ?? 0,
    [run],
  );

  function selectTask(key: string) {
    setSelectedTaskKey(key);
    setMobileInspectorOpen(true);
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-7xl space-y-4 p-6">
        <Skeleton className="h-16" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (isError || !run) {
    return <ErrorState onRetry={() => refetch()} />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-0)] px-6 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[15px] font-semibold tracking-tight text-[var(--color-text-primary)]">
            {run.workflow_name}
          </h1>
          <span className="font-mono text-xs text-[var(--color-text-tertiary)]">
            {formatShortId(run.id)}
          </span>
          <StatusPill status={run.status} />
          {recoveredCount > 0 && (
            <Tooltip content="This task was re-dispatched by the recovery sweep after its original broker message became stale or unavailable.">
              <Badge variant="warning">
                <ShieldCheck className="h-3 w-3" />
                {recoveredCount} recovered
              </Badge>
            </Tooltip>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-tertiary)]">
          <span className="capitalize">{run.trigger_type} trigger</span>
          <span>Started {formatTimestamp(run.started_at)}</span>
          <span className="tabular-nums">
            {run.status === "running"
              ? `Elapsed ${formatElapsed(run.started_at)}`
              : `Duration ${formatDuration(run.duration_ms)}`}
          </span>
        </div>
        {run.error && <p className="mt-2 text-xs text-[var(--color-status-failed)]">{run.error}</p>}

        <div className="mt-3 flex items-stretch divide-x divide-[var(--color-border-subtle)] panel px-4">
          <RailSegment label="Tasks" value={`${run.task_counts.succeeded}/${run.task_counts.total}`} />
          <RailSegment label="Attempts" value={String(totalAttempts)} />
          <RailSegment label="Retries" value={String(run.retry_count)} />
          <RailSegment label="Recovered" value={String(recoveredCount)} />
          <div className="flex min-w-32 flex-1 flex-col justify-center px-4 py-2.5">
            <span className="label-eyebrow">Execution strip</span>
            <div className="mt-1.5">
              <ExecutionStrip tasks={run.tasks} />
            </div>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="px-6 pt-3">
            <Tabs
              tabs={[
                { id: "graph", label: "Graph" },
                { id: "tasks", label: "Tasks" },
              ]}
              active={tab}
              onChange={setTab}
            />
          </div>

          {tab === "graph" ? (
            // The graph fills whatever space remains below the tabs rather
            // than a fixed height: DagView owns its own pan/zoom, so the
            // page itself must never need to scroll to reach the fit-view
            // controls or reveal nodes below the fold.
            <div className="min-h-0 flex-1 p-6 pt-4">
              <div className="flex h-full min-h-96 flex-col panel overflow-hidden">
                <div className="min-h-0 flex-1">
                  <DagView
                    tasks={run.tasks}
                    edges={run.edges}
                    selectedTaskKey={selectedTaskKey}
                    onSelectTask={selectTask}
                  />
                </div>
                <DagLegend />
              </div>
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto p-6 pt-4">
              <TasksTable tasks={run.tasks} selectedTaskKey={selectedTaskKey} onSelect={selectTask} />
            </div>
          )}
        </div>

        <div className="hidden w-80 shrink-0 overflow-y-auto border-l border-[var(--color-border-subtle)] bg-[var(--color-surface-0)] lg:block">
          {selectedTask ? (
            <TaskInspector runId={run.id} task={selectedTask} />
          ) : (
            <div className="p-6 text-center">
              <p className="text-[13px] font-medium text-[var(--color-text-primary)]">
                Task inspector
              </p>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-[var(--color-text-tertiary)]">
                Click any node in the graph to see its status, the worker that
                executed it, its duration, every attempt it made, and the output
                it passed downstream.
              </p>
            </div>
          )}
        </div>
      </div>

      <Sheet
        open={mobileInspectorOpen && !!selectedTask}
        onClose={() => setMobileInspectorOpen(false)}
        title={selectedTask?.task_key}
      >
        {selectedTask && <TaskInspector runId={run.id} task={selectedTask} />}
      </Sheet>
    </div>
  );
}
