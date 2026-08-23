import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface BadgeProps {
  children: ReactNode;
  variant?: "neutral" | "accent" | "warning";
  className?: string;
}

export function Badge({ children, variant = "neutral", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-1.5 py-0.5 text-[11px] font-medium",
        variant === "neutral" &&
          "border-[var(--color-border)] bg-[var(--color-surface-2)] text-[var(--color-text-secondary)]",
        variant === "accent" &&
          "border-[var(--color-accent)]/30 bg-[var(--color-accent-subtle)] text-[var(--color-accent)]",
        variant === "warning" &&
          "border-[var(--color-status-retrying)]/30 bg-[var(--color-status-retrying)]/10 text-[var(--color-status-retrying)]",
        className,
      )}
    >
      {children}
    </span>
  );
}
