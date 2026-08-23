import { ArrowRight, Play, Workflow as WorkflowIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { useWorkflows } from "@/api/queries";
import { StatusPill } from "@/components/StatusPill";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatRelativeTime } from "@/lib/format";

export function Workflows() {
  const { data, isLoading, isError, refetch } = useWorkflows();

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Workflows</h1>
        <p className="text-sm text-[var(--color-text-tertiary)]">
          Declarative DAG definitions available to trigger.
        </p>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={`wf-${i}`} className="h-32" />
          ))}
        </div>
      )}

      {isError && <ErrorState onRetry={() => refetch()} />}

      {data && data.length === 0 && (
        <EmptyState
          icon={WorkflowIcon}
          title="No workflow definitions found"
          description="Workflows are seeded from JSON definitions at startup."
        />
      )}

      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.map((wf) => (
            <Link
              key={wf.key}
              to={`/workflows/${wf.key}`}
              className="group flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)] p-4 transition-colors hover:border-[var(--color-border)] hover:bg-[var(--color-surface-2)]"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
                    {wf.name}
                  </h3>
                  <p className="font-mono text-xs text-[var(--color-text-tertiary)]">{wf.key}</p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-[var(--color-text-tertiary)] transition-transform group-hover:translate-x-0.5" />
              </div>

              {wf.description && (
                <p className="line-clamp-2 text-xs text-[var(--color-text-secondary)]">
                  {wf.description}
                </p>
              )}

              <div className="mt-auto flex items-center justify-between border-t border-[var(--color-border-subtle)] pt-3">
                <span className="text-xs text-[var(--color-text-tertiary)]">
                  {wf.task_count} task{wf.task_count === 1 ? "" : "s"}
                </span>
                {wf.last_run ? (
                  <div className="flex items-center gap-2">
                    <StatusPill status={wf.last_run.status} size="sm" />
                    <span className="text-xs text-[var(--color-text-tertiary)]">
                      {formatRelativeTime(wf.last_run.created_at)}
                    </span>
                  </div>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-[var(--color-text-tertiary)]">
                    <Play className="h-3 w-3" /> Never run
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
