import { Play, Workflow as WorkflowIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { useWorkflows } from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { formatRelativeTime } from "@/lib/format";
import { compareWorkflows, workflowGuide } from "@/lib/workflowGuide";

export function Workflows() {
  const { data, isLoading, isError, refetch } = useWorkflows();

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6 lg:p-8">
      <PageHeader
        title="Workflows"
        subtitle="Every workflow definition seeded into this engine. Each one is a DAG of tasks built to demonstrate a specific execution behaviour — open one to see its graph and run it."
      />

      <div className="panel overflow-hidden">
        {isLoading && <TableSkeleton rows={5} columns={4} />}
        {isError && <ErrorState onRetry={() => refetch()} />}

        {data && data.length === 0 && (
          <EmptyState
            icon={WorkflowIcon}
            title="No workflow definitions found"
            description="Workflows are seeded from JSON definitions at startup."
          />
        )}

        {data && data.length > 0 && (
          <div className="divide-y divide-[var(--color-border-subtle)]">
            {[...data].sort((a, b) => compareWorkflows(a.key, b.key)).map((wf) => (
              <Link
                key={wf.key}
                to={`/workflows/${wf.key}`}
                className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-[var(--color-surface-2)]"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[13px] font-medium text-[var(--color-text-primary)]">
                      {wf.name}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-[var(--color-text-tertiary)]">
                      {wf.key}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12.5px] leading-snug text-[var(--color-text-secondary)]">
                    {workflowGuide(wf.key)?.blurb ?? wf.description}
                  </p>
                </div>

                <span className="hidden shrink-0 font-mono text-xs tabular-nums text-[var(--color-text-tertiary)] sm:block">
                  {wf.task_count} task{wf.task_count === 1 ? "" : "s"}
                </span>

                <div className="w-40 shrink-0 text-right">
                  {wf.last_run ? (
                    <div className="flex items-center justify-end gap-2">
                      <span className="text-xs text-[var(--color-text-tertiary)]">
                        {formatRelativeTime(wf.last_run.created_at)}
                      </span>
                      <StatusPill status={wf.last_run.status} size="sm" bare />
                    </div>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-[var(--color-text-tertiary)]">
                      <Play className="h-3 w-3" /> Never run
                    </span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
