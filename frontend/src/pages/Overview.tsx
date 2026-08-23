import { ListTree } from "lucide-react";
import { Link } from "react-router-dom";
import { useReady, useRuns, useStatsOverview, useWorkers } from "@/api/queries";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/StatusPill";
import { TaskCountsStrip } from "@/components/TaskCountsStrip";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDuration, formatRelativeTime, formatShortId } from "@/lib/format";
import { cn } from "@/lib/utils";

function PulseSegment({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="flex flex-1 flex-col justify-center px-5 py-3.5 first:pl-0 last:pr-0">
      <span className="label-eyebrow">{label}</span>
      <span
        className={cn(
          "mt-1 font-mono text-[22px] font-semibold leading-none tabular-nums",
          tone === "positive" && "text-[var(--color-status-succeeded)]",
          tone === "negative" && "text-[var(--color-status-failed)]",
          !tone && "text-[var(--color-text-primary)]",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function Overview() {
  const stats = useStatsOverview();
  const ready = useReady();
  const recentRuns = useRuns({ limit: 8 });
  const workers = useWorkers();

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="flex items-end justify-between">
        <h1 className="text-[15px] font-semibold tracking-tight text-[var(--color-text-primary)]">
          Overview
        </h1>
        {ready.data && (
          <span className="text-xs text-[var(--color-text-tertiary)]">
            PostgreSQL {ready.data.database.latency_ms?.toFixed(0)}ms · Broker{" "}
            {ready.data.broker.latency_ms?.toFixed(0)}ms
          </span>
        )}
      </div>

      {/* Execution Pulse — one horizontal surface, divided by hairlines,
          rather than a wall of identical metric cards. */}
      {stats.isLoading && <Skeleton className="h-20" />}
      {stats.isError && <ErrorState onRetry={() => stats.refetch()} />}
      {stats.data && (
        <div className="flex items-stretch divide-x divide-[var(--color-border-subtle)] rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-1)] px-5">
          <PulseSegment label="Runs" value={String(stats.data.runs.total)} />
          <PulseSegment
            label="Success rate"
            value={
              stats.data.success_rate != null ? `${Math.round(stats.data.success_rate * 100)}%` : "—"
            }
            tone={
              stats.data.success_rate == null
                ? undefined
                : stats.data.success_rate >= 0.8
                  ? "positive"
                  : "negative"
            }
          />
          <PulseSegment label="Tasks executed" value={String(stats.data.tasks_executed)} />
          <PulseSegment label="Retries" value={String(stats.data.retries)} />
          <PulseSegment label="Recovered" value={String(stats.data.recovered_tasks)} />
          <PulseSegment label="Avg duration" value={formatDuration(stats.data.avg_duration_ms)} />
          {stats.data.daily.length > 0 && (
            <div className="hidden flex-col justify-center px-5 py-3.5 xl:flex">
              <span className="label-eyebrow">14 days</span>
              <div className="mt-1.5">
                <Sparkline daily={stats.data.daily} />
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Recent runs — the dominant content on this page. */}
        <div className="lg:col-span-2 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-2.5">
            <h2 className="text-[13px] font-medium text-[var(--color-text-primary)]">Recent runs</h2>
            <Link to="/runs" className="text-xs text-[var(--color-accent)] hover:underline">
              View all
            </Link>
          </div>

          {recentRuns.isLoading && <Skeleton className="m-4 h-40" />}
          {recentRuns.isError && <ErrorState onRetry={() => recentRuns.refetch()} />}
          {recentRuns.data && recentRuns.data.pages[0].items.length === 0 && (
            <EmptyState
              icon={ListTree}
              title="No runs yet"
              description="Trigger a workflow to see its execution history appear here."
              action={
                <Link
                  to="/workflows"
                  className="inline-flex h-7 items-center justify-center rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-1)] px-2.5 text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-surface-2)]"
                >
                  Browse workflows
                </Link>
              }
            />
          )}
          {recentRuns.data && recentRuns.data.pages[0].items.length > 0 && (
            <div className="divide-y divide-[var(--color-border-subtle)]">
              {recentRuns.data.pages[0].items.map((run) => (
                <Link
                  key={run.id}
                  to={`/runs/${run.id}`}
                  className="flex items-center gap-4 px-4 py-2.5 hover:bg-[var(--color-surface-2)]"
                >
                  <StatusPill status={run.status} size="sm" bare className="w-[92px] shrink-0" />
                  <span className="w-40 shrink-0 truncate text-[13px] text-[var(--color-text-primary)]">
                    {run.workflow_name}
                  </span>
                  <TaskCountsStrip counts={run.task_counts} className="hidden max-w-24 flex-1 sm:block" />
                  <span className="ml-auto shrink-0 font-mono text-xs tabular-nums text-[var(--color-text-tertiary)]">
                    {run.task_counts.succeeded}/{run.task_counts.total}
                  </span>
                  <span className="w-16 shrink-0 text-right text-xs text-[var(--color-text-tertiary)]">
                    {formatRelativeTime(run.created_at)}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Observed workers — secondary panel. */}
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-2.5">
            <h2 className="text-[13px] font-medium text-[var(--color-text-primary)]">
              Observed workers
            </h2>
            <Link to="/workers" className="text-xs text-[var(--color-accent)] hover:underline">
              View all
            </Link>
          </div>
          {workers.isLoading && <Skeleton className="m-4 h-16" />}
          {workers.data && workers.data.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-[var(--color-text-tertiary)]">
              No worker activity observed yet.
            </p>
          )}
          {workers.data && workers.data.length > 0 && (
            <div className="divide-y divide-[var(--color-border-subtle)]">
              {workers.data.slice(0, 6).map((w) => (
                <div key={w.worker_id} className="flex items-center justify-between px-4 py-2 text-sm">
                  <span className="flex items-center gap-2 truncate font-mono text-xs text-[var(--color-text-primary)]">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        w.liveness === "active"
                          ? "bg-[var(--color-status-succeeded)]"
                          : "bg-[var(--color-text-tertiary)]",
                      )}
                    />
                    {formatShortId(w.worker_id)}
                  </span>
                  <span className="shrink-0 text-xs capitalize text-[var(--color-text-tertiary)]">
                    {w.liveness}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
