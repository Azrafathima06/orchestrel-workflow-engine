import { Loader2, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTriggerRun, useWorkflow } from "@/api/queries";
import type { TaskRunSummary } from "@/api/types";
import { DagView } from "@/components/dag/DagView";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatRelativeTime, formatShortId } from "@/lib/format";

interface ParamSchemaField {
  type?: string;
  default?: unknown;
  description?: string;
}

function ParamsForm({
  paramsSchema,
  onSubmit,
  submitting,
}: {
  paramsSchema: Record<string, unknown>;
  onSubmit: (params: Record<string, unknown>) => void;
  submitting: boolean;
}) {
  const fields = Object.entries(paramsSchema) as [string, ParamSchemaField][];
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(([key, spec]) => [key, String(spec.default ?? "")])),
  );

  if (fields.length === 0) {
    return (
      <Button
        variant="primary"
        onClick={() => onSubmit({})}
        disabled={submitting}
      >
        {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        Run workflow
      </Button>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const params: Record<string, unknown> = {};
        for (const [key, spec] of fields) {
          const raw = values[key];
          const isNumeric = spec.type === "integer" || spec.type === "number";
          params[key] = isNumeric && raw !== "" ? Number(raw) : raw;
        }
        onSubmit(params);
      }}
      className="space-y-3"
    >
      {fields.map(([key, spec]) => (
        <div key={key}>
          <label htmlFor={`param-${key}`} className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
            {key}
          </label>
          <input
            id={`param-${key}`}
            type={spec.type === "integer" || spec.type === "number" ? "number" : "text"}
            value={values[key]}
            onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface-0)] px-2.5 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none"
          />
          {spec.description && (
            <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">{spec.description}</p>
          )}
        </div>
      ))}
      <Button type="submit" variant="primary" disabled={submitting} className="w-full">
        {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        Run workflow
      </Button>
    </form>
  );
}

export function WorkflowDetail() {
  const { key } = useParams<{ key: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useWorkflow(key);
  const trigger = useTriggerRun(key ?? "");

  const previewTasks: TaskRunSummary[] = useMemo(() => {
    if (!data) return [];
    return data.nodes.map((n) => ({
      id: n.task_key,
      task_key: n.task_key,
      handler: n.handler,
      status: "pending",
      depends_on: n.depends_on,
      attempt_count: 0,
      max_attempts: n.max_attempts,
      next_attempt_at: null,
      dispatch_count: 0,
      worker_id: null,
      started_at: null,
      finished_at: null,
      duration_ms: null,
      output: null,
      error_type: null,
      error_message: null,
    }));
  }, [data]);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (isError || !data) {
    return <ErrorState onRetry={() => refetch()} />;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">{data.name}</h1>
        <p className="font-mono text-xs text-[var(--color-text-tertiary)]">
          {data.key} · v{data.version} · {data.nodes.length} tasks
        </p>
        {data.description && (
          <p className="mt-1.5 max-w-2xl text-sm text-[var(--color-text-secondary)]">
            {data.description}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          <div className="h-80 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            <DagView tasks={previewTasks} edges={data.edges} />
          </div>

          <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border-subtle)] text-left text-xs text-[var(--color-text-tertiary)]">
                    <th className="px-4 py-2 font-medium">Task</th>
                    <th className="px-4 py-2 font-medium">Handler</th>
                    <th className="px-4 py-2 font-medium">Depends on</th>
                    <th className="px-4 py-2 font-medium">Max attempts</th>
                    <th className="px-4 py-2 font-medium">Timeout</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border-subtle)]">
                  {data.nodes.map((n) => (
                    <tr key={n.task_key}>
                      <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-primary)]">
                        {n.task_key}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-[var(--color-text-secondary)]">
                        {n.handler}
                      </td>
                      <td className="px-4 py-2 text-xs text-[var(--color-text-tertiary)]">
                        {n.depends_on.length > 0 ? n.depends_on.join(", ") : "—"}
                      </td>
                      <td className="px-4 py-2 text-xs tabular-nums text-[var(--color-text-tertiary)]">
                        {n.max_attempts}
                      </td>
                      <td className="px-4 py-2 text-xs tabular-nums text-[var(--color-text-tertiary)]">
                        {n.timeout_seconds}s
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)] p-4">
            <h2 className="mb-3 text-sm font-medium text-[var(--color-text-primary)]">
              Trigger a run
            </h2>
            <ParamsForm
              paramsSchema={data.params_schema}
              submitting={trigger.isPending}
              onSubmit={(params) => {
                trigger.mutate(
                  { params },
                  {
                    onSuccess: (run) => navigate(`/runs/${run.id}`),
                  },
                );
              }}
            />
            {trigger.isError && (
              <p className="mt-2 text-xs text-[var(--color-status-failed)]">
                Couldn't start the run. Please try again.
              </p>
            )}
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
              <h2 className="text-sm font-medium text-[var(--color-text-primary)]">Recent runs</h2>
            </div>
            {data.recent_runs.length === 0 ? (
              <p className="px-4 py-6 text-center text-xs text-[var(--color-text-tertiary)]">
                No runs yet.
              </p>
            ) : (
              <div className="divide-y divide-[var(--color-border-subtle)]">
                {data.recent_runs.map((run) => (
                  <Link
                    key={run.id}
                    to={`/runs/${run.id}`}
                    className="flex items-center justify-between px-4 py-2.5 hover:bg-[var(--color-surface-2)]"
                  >
                    <div className="flex items-center gap-2">
                      <StatusPill status={run.status} size="sm" />
                      <span className="font-mono text-xs text-[var(--color-text-tertiary)]">
                        {formatShortId(run.id)}
                      </span>
                    </div>
                    <span className="text-xs text-[var(--color-text-tertiary)]">
                      {formatRelativeTime(run.created_at)}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
