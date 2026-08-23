import { AlertTriangle } from "lucide-react";
import { useTaskDetail } from "@/api/queries";
import type { TaskRunSummary } from "@/api/types";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { AttemptList } from "./AttemptList";
import { RetryCountdown } from "./RetryCountdown";
import { StatusPill } from "./StatusPill";
import { Skeleton } from "./ui/Skeleton";

interface TaskInspectorProps {
  runId: string;
  task: TaskRunSummary;
}

function TaskRefRow({ taskKey, status }: { taskKey: string; status: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] px-2.5 py-1.5">
      <span className="font-mono text-xs text-[var(--color-text-primary)]">{taskKey}</span>
      <StatusPill status={status} size="sm" />
    </div>
  );
}

export function TaskInspector({ runId, task }: TaskInspectorProps) {
  const { data, isLoading, isError, refetch } = useTaskDetail(runId, task.id);

  return (
    <div className="flex flex-col gap-5 p-4">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h3 className="truncate font-mono text-sm font-semibold text-[var(--color-text-primary)]">
            {task.task_key}
          </h3>
          <StatusPill status={task.status} />
        </div>
        <p className="mt-0.5 font-mono text-xs text-[var(--color-text-tertiary)]">{task.handler}</p>
      </div>

      {task.status === "retrying" && task.next_attempt_at && (
        <div className="rounded-md border border-[var(--color-status-retrying)]/25 bg-[var(--color-status-retrying)]/10 px-3 py-2 text-sm text-[var(--color-status-retrying)]">
          <RetryCountdown nextAttemptAt={task.next_attempt_at} />
          <p className="mt-0.5 text-xs opacity-80">
            attempt {task.attempt_count + 1} of {task.max_attempts}
          </p>
        </div>
      )}

      {task.status === "upstream_failed" && (
        <div className="flex items-start gap-2 rounded-md border border-[var(--color-status-upstream-failed)]/25 bg-[var(--color-status-upstream-failed)]/10 px-3 py-2 text-xs text-[var(--color-status-upstream-failed)]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div>
            <p className="font-medium">
              This task never executed because a required upstream task failed.
            </p>
            {task.error_message && <p className="mt-1 opacity-90">{task.error_message}</p>}
          </div>
        </div>
      )}

      {task.status === "failed" && task.error_type && (
        <div className="rounded-md border border-[var(--color-status-failed)]/25 bg-[var(--color-status-failed)]/10 px-3 py-2 text-xs text-[var(--color-status-failed)]">
          <p className="font-medium">Handler executed and failed.</p>
          <p className="mt-1 font-mono">{task.error_type}</p>
          {task.error_message && <p className="mt-1 opacity-90">{task.error_message}</p>}
        </div>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5 text-xs">
        <div>
          <dt className="text-[var(--color-text-tertiary)]">Attempts</dt>
          <dd className="mt-0.5 font-mono tabular-nums text-[var(--color-text-primary)]">
            {task.attempt_count} / {task.max_attempts}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-tertiary)]">Worker</dt>
          <dd className="mt-0.5 truncate font-mono text-[var(--color-text-primary)]">
            {task.worker_id ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-tertiary)]">Duration</dt>
          <dd className="mt-0.5 font-mono tabular-nums text-[var(--color-text-primary)]">
            {formatDuration(task.duration_ms)}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-tertiary)]">Started</dt>
          <dd className="mt-0.5 text-[var(--color-text-primary)]">
            {formatTimestamp(task.started_at)}
          </dd>
        </div>
      </dl>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}

      {isError && (
        <button
          type="button"
          onClick={() => refetch()}
          className="text-xs text-[var(--color-accent)] hover:underline"
        >
          Couldn't load task detail — retry
        </button>
      )}

      {data && (
        <>
          {(data.dependencies.length > 0 || data.dependents.length > 0) && (
            <div className="grid grid-cols-2 gap-3">
              {data.dependencies.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-[var(--color-text-tertiary)]">
                    Dependencies
                  </p>
                  <div className="space-y-1">
                    {data.dependencies.map((d) => (
                      <TaskRefRow key={d.task_run_id} taskKey={d.task_key} status={d.status} />
                    ))}
                  </div>
                </div>
              )}
              {data.dependents.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-[var(--color-text-tertiary)]">
                    Dependents
                  </p>
                  <div className="space-y-1">
                    {data.dependents.map((d) => (
                      <TaskRefRow key={d.task_run_id} taskKey={d.task_key} status={d.status} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div>
            <p className="mb-1.5 text-xs font-medium text-[var(--color-text-tertiary)]">
              Attempt history
            </p>
            <AttemptList attempts={data.attempts} />
          </div>

          {data.output && (
            <div>
              <p className="mb-1.5 text-xs font-medium text-[var(--color-text-tertiary)]">Output</p>
              <pre className="max-h-40 overflow-auto rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] p-2.5 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
                {JSON.stringify(data.output, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}
