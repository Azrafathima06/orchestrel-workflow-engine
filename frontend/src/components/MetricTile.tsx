import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface MetricTileProps {
  label: string;
  value: string;
  icon: LucideIcon;
  hint?: string;
  tone?: "neutral" | "positive" | "negative";
}

export function MetricTile({ label, value, icon: Icon, hint, tone = "neutral" }: MetricTileProps) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-1)] p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--color-text-tertiary)]">{label}</span>
        <Icon className="h-3.5 w-3.5 text-[var(--color-text-tertiary)]" strokeWidth={1.75} />
      </div>
      <p
        className={cn(
          "mt-2 font-mono text-2xl font-semibold tabular-nums",
          tone === "neutral" && "text-[var(--color-text-primary)]",
          tone === "positive" && "text-[var(--color-status-succeeded)]",
          tone === "negative" && "text-[var(--color-status-failed)]",
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">{hint}</p>}
    </div>
  );
}
