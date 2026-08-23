import type { ReactNode } from "react";

/** Lightweight CSS-only tooltip: no positioning library, no JS state. */
export function Tooltip({ content, children }: { content: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 w-max max-w-64 -translate-x-1/2 scale-95 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-1.5 text-xs text-[var(--color-text-secondary)] opacity-0 shadow-lg transition-all duration-100 group-hover:scale-100 group-hover:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}
