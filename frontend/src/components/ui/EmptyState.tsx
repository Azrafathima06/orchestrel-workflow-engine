import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)]">
        <Icon className="h-5 w-5 text-[var(--color-text-tertiary)]" strokeWidth={1.75} />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-[var(--color-text-primary)]">{title}</p>
        {description && (
          <p className="max-w-sm text-sm text-[var(--color-text-tertiary)]">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
