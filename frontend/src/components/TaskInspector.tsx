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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="px-4 py-3.5">
      <h4 className="label-eyebrow mb-2.5">{title}</h4>
      {children}
    </section>
  );
}

function TaskRefRow({ taskKey, status }: { taskKey: string; status: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="font-mono text-xs text-[var(--color-text-primary)]">{taskKey}</span>
      <StatusPill status={status} size="sm" bare />
    </div>
  );
}

export function TaskInspector({ runId, task }: TaskInspectorProps) {
  const { data, isLoading, isError, refetch } = useTaskDetail(runId, task.id);

  return (
    <div className="flex flex-col divide-y divide-[var(--color-border-subtle)]">
      <div className="px-4 py-3.5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="truncate font-mono text-[13px] font-semibold text-[var(--color-text-primary)]">
            {task.task_key}
          </h3>
          <StatusPill status={task.status} size="sm" />
        </div>
        <p className="mt-0.5 font-mono text-xs text-[var(--color-text-tertiary)]">{task.handler}</p>

        {task.status === "retrying" && task.next_attempt_at && (
          <div className="mt-3 border-l-2 border-[var(--color-status-retrying)] pl-2.5 text-xs text-[var(--color-status-retrying)]">
            <p className="font-medium tracking-tight">
              RETRYING · attempt {task.attempt_count + 1} of {task.max_attempts}
            </p>
            <p className="mt-0.5 opacity-85">
              <RetryCountdown nextAttemptAt={task.next_attempt_at} />
            </p>
          </div>
        )}

        {task.status === "upstream_failed" && (
          <div className="mt-3 flex items-start gap-2 border-l-2 border-[var(--color-status-upstream-failed)] pl-2.5 text-xs text-[var(--color-status-upstream-failed)]">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              <p className="font-medium">
                Never executed — a required upstream task failed.
              </p>
              {task.error_message && <p className="mt-1 opacity-90">{task.error_message}</p>}
            </div>
          </div>
        )}

        {task.status === "failed" && task.error_type && (
          <div className="mt-3 border-l-2 border-[var(--color-status-failed)] pl-2.5 text-xs text-[var(--color-status-failed)]">
            <p className="font-medium">Handler executed and failed.</p>
            <p className="mt-1 font-mono">{task.error_type}</p>
            {task.error_message && <p className="mt-1 opacity-90">{task.error_message}</p>}
          </div>
        )}
      </div>

      <Section title="Execution">
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
      </Section>

      {isLoading && (
        <div className="space-y-2 px-4 py-3.5">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}

      {isError && (
        <div className="px-4 py-3.5">
          <button
            type="button"
            onClick={() => refetch()}
            className="text-xs text-[var(--color-accent)] hover:underline"
          >
            Couldn't load task detail — retry
          </button>
        </div>
      )}

      {data && (
        <>
          {(data.dependencies.length > 0 || data.dependents.length > 0) && (
            <Section title="Dependencies">
              <div className="grid grid-cols-2 gap-3">
                {data.dependencies.length > 0 && (
                  <div>
                    <p className="mb-1 text-[11px] text-[var(--color-text-tertiary)]">Depends on</p>
                    <div>
                      {data.dependencies.map((d) => (
                        <TaskRefRow key={d.task_run_id} taskKey={d.task_key} status={d.status} />
                      ))}
                    </div>
                  </div>
                )}
                {data.dependents.length > 0 && (
                  <div>
                    <p className="mb-1 text-[11px] text-[var(--color-text-tertiary)]">Feeds into</p>
                    <div>
                      {data.dependents.map((d) => (
                        <TaskRefRow key={d.task_run_id} taskKey={d.task_key} status={d.status} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Section>
          )}

          <Section title="Attempts">
            <AttemptList attempts={data.attempts} />
          </Section>

          {data.output && (
            <Section title="Output">
              <pre className="max-h-40 overflow-auto rounded-[var(--radius-sm)] bg-[var(--color-surface-0)] p-2.5 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
                {JSON.stringify(data.output, null, 2)}
              </pre>
            </Section>
          )}
        </>
      )}
    </div>
  );
}
