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
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
        "disabled:pointer-events-none disabled:opacity-50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/50",
        size === "md" && "h-9 px-3.5 text-sm",
        size === "sm" && "h-7 px-2.5 text-xs",
        variant === "primary" &&
          "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)]",
        variant === "secondary" &&
          "border border-[var(--color-border)] bg-[var(--color-surface-1)] text-[var(--color-text-primary)] hover:bg-[var(--color-surface-2)]",
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
