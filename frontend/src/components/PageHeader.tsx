import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  /** One line saying what this page is for. Present on every page: the
   *  dashboard is read by people who have never seen a workflow engine. */
  subtitle?: string;
  /** Right-aligned metadata or controls. */
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2 pt-1">{actions}</div>}
    </div>
  );
}
