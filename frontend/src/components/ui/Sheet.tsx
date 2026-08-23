import { X } from "lucide-react";
import type { ReactNode } from "react";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}

/** Slide-in panel used for the task inspector on narrow viewports. */
export function Sheet({ open, onClose, title, children }: SheetProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end lg:hidden">
      <button
        type="button"
        aria-label="Close panel"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />
      <div className="relative flex h-full w-full max-w-sm flex-col border-l border-[var(--color-border)] bg-[var(--color-surface-1)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-4 py-3">
          <span className="text-sm font-medium text-[var(--color-text-primary)]">{title}</span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-[var(--color-text-tertiary)] hover:bg-[var(--color-surface-2)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
