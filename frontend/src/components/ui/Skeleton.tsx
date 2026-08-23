import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-[var(--color-surface-2)]", className)}
      aria-hidden
    />
  );
}

/** Skeleton rows matching a table's real column layout, for the loading state of dense lists. */
export function TableSkeleton({ rows = 6, columns = 6 }: { rows?: number; columns?: number }) {
  return (
    <div className="divide-y divide-[var(--color-border-subtle)]">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={`row-${r}`} className="flex items-center gap-4 px-4 py-3">
          {Array.from({ length: columns }).map((__, c) => (
            <Skeleton key={`cell-${c}`} className={c === 0 ? "h-4 w-20" : "h-4 flex-1"} />
          ))}
        </div>
      ))}
    </div>
  );
}
