import { Server } from "lucide-react";
import { useWorkers } from "@/api/queries";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { formatRelativeTime, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

const LIVENESS_STYLE: Record<string, string> = {
  active: "text-[var(--color-status-succeeded)] bg-[var(--color-status-succeeded)]/10 border-[var(--color-status-succeeded)]/25",
  idle: "text-[var(--color-text-secondary)] bg-[var(--color-surface-2)] border-[var(--color-border)]",
  stale: "text-[var(--color-text-tertiary)] bg-[var(--color-surface-2)] border-[var(--color-border)]",
};

export function Workers() {
  const { data, isLoading, isError, refetch } = useWorkers();

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">
          Workers observed executing tasks
        </h1>
        <p className="max-w-2xl text-sm text-[var(--color-text-tertiary)]">
          Derived from persisted task-attempt history — not a Celery remote-control heartbeat.
          A worker that is running but idle looks identical to one that isn't running at all,
          which is why liveness below reflects observed activity rather than an "online" claim.
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)]">
        {isLoading && <TableSkeleton rows={4} columns={6} />}
        {isError && <ErrorState onRetry={() => refetch()} />}

        {data && data.length === 0 && (
          <EmptyState
            icon={Server}
            title="No worker activity observed yet"
            description="Trigger a workflow to see executing workers appear here."
          />
        )}

        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border-subtle)] text-left text-xs text-[var(--color-text-tertiary)]">
                  <th className="px-4 py-2 font-medium">Worker ID</th>
                  <th className="px-4 py-2 font-medium">Liveness</th>
                  <th className="px-4 py-2 font-medium">Currently running</th>
                  <th className="px-4 py-2 font-medium">Attempts (1h)</th>
                  <th className="px-4 py-2 font-medium">Attempts (total)</th>
                  <th className="px-4 py-2 font-medium">Last seen</th>
                  <th className="px-4 py-2 font-medium">First seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border-subtle)]">
                {data.map((w) => (
                  <tr key={w.worker_id}>
                    <td className="px-4 py-2.5 font-mono text-xs text-[var(--color-text-primary)]">
                      {w.worker_id}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
                          LIVENESS_STYLE[w.liveness],
                        )}
                      >
                        {w.liveness}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs tabular-nums text-[var(--color-text-tertiary)]">
                      {w.currently_running}
                    </td>
                    <td className="px-4 py-2.5 text-xs tabular-nums text-[var(--color-text-tertiary)]">
                      {w.attempts_1h}
                    </td>
                    <td className="px-4 py-2.5 text-xs tabular-nums text-[var(--color-text-tertiary)]">
                      {w.attempts_total}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[var(--color-text-tertiary)]">
                      {formatRelativeTime(w.last_seen_at)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[var(--color-text-tertiary)]">
                      {formatTimestamp(w.first_seen_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
