import { ArrowRight, ListTree, Workflow as WorkflowIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { useReady, useRuns, useStatsOverview, useWorkers, useWorkflows } from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/StatusPill";
import { TaskCountsStrip } from "@/components/TaskCountsStrip";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDuration, formatRelativeTime, formatShortId } from "@/lib/format";
import { compareWorkflows, workflowGuide } from "@/lib/workflowGuide";
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
    <div className="flex flex-1 flex-col justify-center px-5 py-4 first:pl-0 last:pr-0">
      <span className="label-eyebrow">{label}</span>
      <span
        className={cn(
          "stat-value mt-2",
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

/**
 * Orientation strip for anyone arriving straight at the dashboard — from a
 * bookmark, a shared run link, or the sidebar — who skipped the landing
 * page and its explanation of what any of this is.
 */
function QuickStart() {
  const { data } = useWorkflows();
  const suggestions = (data ?? [])
    .filter((w) => w.is_public)
    .sort((a, b) => compareWorkflows(a.key, b.key))
    .slice(0, 3);

  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-[var(--color-border-subtle)] px-5 py-3.5">
        <h2 className="text-[13.5px] font-semibold text-[var(--color-text-primary)]">
          New here? Run a workflow
        </h2>
        <Link
          to="/"
          className="text-[12px] text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
        >
          What is Orchestrel?
        </Link>
      </div>

      <div className="grid grid-cols-1 divide-y divide-[var(--color-border-subtle)] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {suggestions.map((wf, i) => {
          const guide = workflowGuide(wf.key);
          const Icon = guide?.icon ?? WorkflowIcon;
          const accent = guide?.accentVar ?? "--color-accent";

          return (
            <Link
              key={wf.key}
              to={`/workflows/${wf.key}`}
              className="group flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-[var(--color-surface-2)]"
            >
              <div className="flex items-center gap-2.5">
                <span className="font-mono text-[11px] text-[var(--color-text-tertiary)]">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <Icon
                  className="h-3.5 w-3.5 shrink-0"
                  style={{ color: `var(${accent})` }}
                  strokeWidth={2}
                />
                <span className="truncate text-[13.5px] font-medium text-[var(--color-text-primary)]">
                  {guide?.headline ?? wf.name}
                </span>
                <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0 text-[var(--color-text-tertiary)] transition-transform group-hover:translate-x-0.5" />
              </div>
              <p className="text-[12.5px] leading-[1.55] text-[var(--color-text-secondary)]">
                {guide?.blurb ?? wf.description}
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export function Overview() {
  const stats = useStatsOverview();
  const ready = useReady();
  const recentRuns = useRuns({ limit: 8 });
  const workers = useWorkers();

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6 lg:p-8">
      <PageHeader
        title="Overview"
        subtitle="Aggregate execution health across every workflow run this engine has performed. All figures are computed from persisted run and attempt records."
        actions={
          ready.data && (
            <span className="font-mono text-[11.5px] text-[var(--color-text-tertiary)]">
              PostgreSQL {ready.data.database.latency_ms?.toFixed(0)}ms · Broker{" "}
              {ready.data.broker.latency_ms?.toFixed(0)}ms
            </span>
          )
        }
      />

      {/* Execution Pulse — one horizontal surface, divided by hairlines,
          rather than a wall of identical metric cards. */}
      {stats.isLoading && <Skeleton className="h-24" />}
      {stats.isError && <ErrorState onRetry={() => stats.refetch()} />}
      {stats.data && (
        <div className="panel flex items-stretch divide-x divide-[var(--color-border-subtle)] px-5">
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
            <div className="hidden flex-col justify-center px-5 py-4 xl:flex">
              <span className="label-eyebrow">14 days</span>
              <div className="mt-2.5">
                <Sparkline daily={stats.data.daily} />
              </div>
            </div>
          )}
        </div>
      )}

      <QuickStart />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Recent runs — the dominant content on this page. */}
        <div className="panel lg:col-span-2">
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-5 py-3.5">
            <h2 className="text-[13.5px] font-semibold text-[var(--color-text-primary)]">
              Recent runs
            </h2>
            <Link
              to="/runs"
              className="text-[12px] font-medium text-[var(--color-accent)] hover:underline"
            >
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
                  className="inline-flex h-8 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-accent)] px-3 text-[13px] font-medium text-white hover:bg-[var(--color-accent-hover)]"
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
                  className="flex items-center gap-4 px-5 py-3 transition-colors hover:bg-[var(--color-surface-2)]"
                >
                  <StatusPill status={run.status} size="sm" bare className="w-[104px] shrink-0" />
                  <span className="w-44 shrink-0 truncate text-[13.5px] text-[var(--color-text-primary)]">
                    {run.workflow_name}
                  </span>
                  <TaskCountsStrip
                    counts={run.task_counts}
                    className="hidden max-w-24 flex-1 sm:block"
                  />
                  <span className="ml-auto shrink-0 font-mono text-[12px] tabular-nums text-[var(--color-text-tertiary)]">
                    {run.task_counts.succeeded}/{run.task_counts.total}
                  </span>
                  <span className="w-16 shrink-0 text-right text-[12px] text-[var(--color-text-tertiary)]">
                    {formatRelativeTime(run.created_at)}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Observed workers — secondary panel. */}
        <div className="panel">
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-5 py-3.5">
            <h2 className="text-[13.5px] font-semibold text-[var(--color-text-primary)]">
              Observed workers
            </h2>
            <Link
              to="/workers"
              className="text-[12px] font-medium text-[var(--color-accent)] hover:underline"
            >
              View all
            </Link>
          </div>
          <p className="border-b border-[var(--color-border-subtle)] px-5 py-2.5 text-[12px] leading-snug text-[var(--color-text-tertiary)]">
            Processes seen executing tasks, derived from attempt history.
          </p>
          {workers.isLoading && <Skeleton className="m-4 h-16" />}
          {workers.data && workers.data.length === 0 && (
            <p className="px-5 py-6 text-center text-[12.5px] text-[var(--color-text-tertiary)]">
              No worker activity observed yet.
            </p>
          )}
          {workers.data && workers.data.length > 0 && (
            <div className="divide-y divide-[var(--color-border-subtle)]">
              {workers.data.slice(0, 6).map((w) => (
                <div
                  key={w.worker_id}
                  className="flex items-center justify-between px-5 py-2.5 text-sm"
                >
                  <span className="flex items-center gap-2.5 truncate font-mono text-[12px] text-[var(--color-text-primary)]">
                    <span className="relative flex h-1.5 w-1.5 shrink-0">
                      {w.liveness === "active" && (
                        <span className="absolute inline-flex h-full w-full rounded-full bg-[var(--color-status-succeeded)] animate-ring" />
                      )}
                      <span
                        className={cn(
                          "relative inline-flex h-1.5 w-1.5 rounded-full",
                          w.liveness === "active"
                            ? "bg-[var(--color-status-succeeded)]"
                            : "bg-[var(--color-text-tertiary)]",
                        )}
                      />
                    </span>
                    {formatShortId(w.worker_id)}
                  </span>
                  <span className="shrink-0 text-[12px] capitalize text-[var(--color-text-tertiary)]">
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
