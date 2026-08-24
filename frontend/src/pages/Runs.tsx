import { ListTree, Loader2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useRuns, useWorkflows } from "@/api/queries";
import type { WorkflowStatus } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { TaskCountsStrip } from "@/components/TaskCountsStrip";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { formatDuration, formatRelativeTime, formatShortId } from "@/lib/format";

const STATUS_OPTIONS: { value: WorkflowStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function Select({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-7 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] px-2 text-xs text-[var(--color-text-secondary)] focus:border-[var(--color-accent)] focus:outline-none"
    >
      {children}
    </select>
  );
}

export function Runs() {
  const [status, setStatus] = useState<WorkflowStatus | "">("");
  const [workflow, setWorkflow] = useState("");

  const navigate = useNavigate();
  const workflows = useWorkflows();
  const runs = useRuns({
    status: status || undefined,
    workflow: workflow || undefined,
    limit: 25,
  });

  const items = runs.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6 lg:p-8">
      <PageHeader
        title="Run history"
        subtitle="Every execution this engine has performed, newest first. Open a run to see its graph, per-task state and full attempt timeline."
        actions={
          <>
          <Select value={status} onChange={(v) => setStatus(v as WorkflowStatus | "")}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
          <Select value={workflow} onChange={setWorkflow}>
            <option value="">All workflows</option>
            {workflows.data?.map((w) => (
              <option key={w.key} value={w.key}>
                {w.name}
              </option>
            ))}
          </Select>
          </>
        }
      />

      <div className="panel overflow-hidden">
        {runs.isLoading && <TableSkeleton rows={8} columns={7} />}
        {runs.isError && <ErrorState onRetry={() => runs.refetch()} />}

        {items.length === 0 && !runs.isLoading && !runs.isError && (
          <EmptyState
            icon={ListTree}
            title="No runs match these filters"
            description="Try a different status or workflow, or trigger a new run."
          />
        )}

        {items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border-subtle)] text-left">
                  <th className="label-eyebrow px-4 py-2 font-medium">Status</th>
                  <th className="label-eyebrow px-4 py-2 font-medium">Workflow</th>
                  <th className="label-eyebrow px-4 py-2 font-medium">Run</th>
                  <th className="label-eyebrow px-4 py-2 font-medium">Trigger</th>
                  <th className="label-eyebrow px-4 py-2 font-medium">Created</th>
                  <th className="label-eyebrow px-4 py-2 text-right font-medium">Duration</th>
                  <th className="label-eyebrow px-4 py-2 font-medium">Progress</th>
                  <th className="label-eyebrow px-4 py-2 text-right font-medium">Retries</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border-subtle)]">
                {items.map((run) => (
                  <tr
                    key={run.id}
                    className="cursor-pointer transition-colors hover:bg-[var(--color-surface-2)]"
                    onClick={() => navigate(`/runs/${run.id}`)}
                  >
                    <td className="px-4 py-2.5">
                      <StatusPill status={run.status} size="sm" />
                    </td>
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/runs/${run.id}`}
                        className="text-[13px] text-[var(--color-text-primary)] hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {run.workflow_name}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-[var(--color-text-tertiary)]">
                      {formatShortId(run.id)}
                    </td>
                    <td className="px-4 py-2.5 text-xs capitalize text-[var(--color-text-tertiary)]">
                      {run.trigger_type}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[var(--color-text-tertiary)]">
                      {formatRelativeTime(run.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs tabular-nums text-[var(--color-text-tertiary)]">
                      {formatDuration(run.duration_ms)}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="w-9 shrink-0 font-mono text-xs tabular-nums text-[var(--color-text-tertiary)]">
                          {run.task_counts.succeeded}/{run.task_counts.total}
                        </span>
                        <TaskCountsStrip counts={run.task_counts} className="w-16 shrink-0" />
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs tabular-nums text-[var(--color-text-tertiary)]">
                      {run.retry_count > 0 ? run.retry_count : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {runs.hasNextPage && (
          <div className="flex justify-center border-t border-[var(--color-border-subtle)] p-3">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => runs.fetchNextPage()}
              disabled={runs.isFetchingNextPage}
            >
              {runs.isFetchingNextPage && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Load more
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
