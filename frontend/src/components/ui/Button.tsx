import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
}

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] font-medium transition-colors duration-150",
        "disabled:pointer-events-none disabled:opacity-50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/50",
        size === "md" && "h-8 px-3 text-[13px]",
        size === "sm" && "h-6.5 px-2 text-xs",
        variant === "primary" &&
          "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] active:bg-[var(--color-accent-hover)]",
        variant === "secondary" &&
          "border border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] text-[var(--color-text-primary)] hover:border-[var(--color-border)] hover:bg-[var(--color-surface-2)]",
        variant === "ghost" &&
          "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text-primary)]",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
