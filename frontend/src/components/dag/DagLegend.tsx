import { statusMeta, type Status } from "@/lib/status";

/**
 * Reading a DAG correctly depends on one distinction that is not obvious to
 * someone meeting the engine for the first time: FAILED means the handler
 * ran and raised, while UPSTREAM_FAILED means the task never executed at
 * all because something it depended on failed. Those two are what "failure
 * isolation" actually looks like on screen, so the legend spells them out
 * rather than only showing swatches.
 */
const ENTRIES: { status: Status; note: string }[] = [
  { status: "succeeded", note: "handler completed" },
  { status: "running", note: "executing now" },
  { status: "retrying", note: "waiting on backoff" },
  { status: "failed", note: "ran and errored" },
  { status: "upstream_failed", note: "never ran — a dependency failed" },
  { status: "pending", note: "dependencies not yet satisfied" },
];

export function DagLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--color-border-subtle)] px-4 py-2.5">
      {ENTRIES.map(({ status, note }) => {
        const meta = statusMeta(status);
        return (
          <span key={status} className="flex items-center gap-1.5 text-[11.5px] whitespace-nowrap">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: `var(${meta.cssVar})` }}
            />
            <span className="font-medium text-[var(--color-text-secondary)]">{meta.label}</span>
            <span className="text-[var(--color-text-tertiary)]">{note}</span>
          </span>
        );
      })}
    </div>
  );
}
