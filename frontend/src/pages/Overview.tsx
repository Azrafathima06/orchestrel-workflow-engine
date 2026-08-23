import {
  Activity,
  CheckCircle2,
  Clock,
  ListTree,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useReady, useRuns, useStatsOverview, useWorkers } from "@/api/queries";
import { MetricTile } from "@/components/MetricTile";
import { StatusPill } from "@/components/StatusPill";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDuration, formatRelativeTime, formatShortId } from "@/lib/format";
import { cn } from "@/lib/utils";

function ReadinessRow({ label, ok, latencyMs }: { label: string; ok: boolean; latencyMs: number | null }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-[var(--color-text-secondary)]">{label}</span>
      <span className="flex items-center gap-2">
        {latencyMs != null && (
          <span className="font-mono text-xs tabular-nums text-[var(--color-text-tertiary)]">
            {latencyMs.toFixed(0)}ms
          </span>
        )}
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            ok ? "bg-[var(--color-status-succeeded)]" : "bg-[var(--color-status-failed)]",
          )}
        />
      </span>
    </div>
  );
}

export function Overview() {
  const stats = useStatsOverview();
  const ready = useReady();
  const recentRuns = useRuns({ limit: 6 });
  const workers = useWorkers();

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Overview</h1>
        <p className="text-sm text-[var(--color-text-tertiary)]">
          Real-time status of the workflow engine, from persisted execution state.
        </p>
      </div>

      {stats.isLoading && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={`metric-${i}`} className="h-24" />
          ))}
        </div>
      )}

      {stats.isError && <ErrorState onRetry={() => stats.refetch()} />}

      {stats.data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <MetricTile label="Runs" value={String(stats.data.runs.total)} icon={ListTree} />
          <MetricTile
            label="Success rate"
            value={
              stats.data.success_rate != null ? `${Math.round(stats.data.success_rate * 100)}%` : "—"
            }
            icon={CheckCircle2}
            tone={
              stats.data.success_rate == null
                ? "neutral"
                : stats.data.success_rate >= 0.8
                  ? "positive"
                  : "negative"
            }
          />
          <MetricTile
            label="Tasks executed"
            value={String(stats.data.tasks_executed)}
            icon={Activity}
          />
          <MetricTile label="Retries" value={String(stats.data.retries)} icon={RotateCw} />
          <MetricTile
            label="Recovered tasks"
            value={String(stats.data.recovered_tasks)}
            icon={ShieldCheck}
            hint="stale-message or worker-loss recovery"
          />
          <MetricTile
            label="Avg run duration"
            value={formatDuration(stats.data.avg_duration_ms)}
            icon={Clock}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)]">
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
            <h2 className="text-sm font-medium text-[var(--color-text-primary)]">Recent runs</h2>
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
              description="Trigger a workflow to see it appear here."
              action={
                <Link
                  to="/workflows"
                  className="inline-flex h-7 items-center justify-center rounded-md border border-[var(--color-border)] bg-[var(--color-surface-1)] px-2.5 text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-surface-2)]"
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
                  className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-[var(--color-surface-2)]"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <StatusPill status={run.status} size="sm" />
                    <span className="truncate text-sm text-[var(--color-text-primary)]">
                      {run.workflow_name}
                    </span>
                    <span className="shrink-0 font-mono text-xs text-[var(--color-text-tertiary)]">
                      {formatShortId(run.id)}
                    </span>
                  </div>
                  <span className="shrink-0 text-xs text-[var(--color-text-tertiary)]">
                    {formatRelativeTime(run.created_at)}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)] p-4">
            <h2 className="mb-2 text-sm font-medium text-[var(--color-text-primary)]">
              System readiness
            </h2>
            {ready.isLoading && <Skeleton className="h-16" />}
            {ready.data && (
              <div className="divide-y divide-[var(--color-border-subtle)]">
                <ReadinessRow
                  label="PostgreSQL"
                  ok={ready.data.database.ok}
                  latencyMs={ready.data.database.latency_ms}
                />
                <ReadinessRow
                  label="Broker"
                  ok={ready.data.broker.ok}
                  latencyMs={ready.data.broker.latency_ms}
                />
              </div>
            )}
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
              <h2 className="text-sm font-medium text-[var(--color-text-primary)]">
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
                {workers.data.slice(0, 4).map((w) => (
                  <div key={w.worker_id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <span className="truncate font-mono text-xs text-[var(--color-text-primary)]">
                      {w.worker_id}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 text-xs capitalize",
                        w.liveness === "active"
                          ? "text-[var(--color-status-succeeded)]"
                          : "text-[var(--color-text-tertiary)]",
                      )}
                    >
                      {w.liveness}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
