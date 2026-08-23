import { cn } from "@/lib/utils";

/**
 * Product mark: one source node branching into two dependent nodes along
 * short paths — a minimal dependency graph, standing in for the DAGs this
 * engine orchestrates. Pure geometry — no generated image, no stock icon.
 */
export function OrchestrelMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-accent-subtle)]",
        className,
      )}
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <title>Orchestrel</title>
        <path
          d="M2.5 7 L10.75 3.25"
          stroke="var(--color-accent)"
          strokeWidth="1.4"
          strokeLinecap="round"
          opacity="0.85"
        />
        <path
          d="M2.5 7 L10.75 10.75"
          stroke="var(--color-accent)"
          strokeWidth="1.4"
          strokeLinecap="round"
          opacity="0.6"
        />
        <circle cx="2.5" cy="7" r="1.75" fill="var(--color-accent)" />
        <circle cx="11.5" cy="3" r="1.5" fill="var(--color-accent)" opacity="0.85" />
        <circle cx="11.5" cy="11" r="1.5" fill="var(--color-accent)" opacity="0.6" />
      </svg>
    </div>
  );
}
