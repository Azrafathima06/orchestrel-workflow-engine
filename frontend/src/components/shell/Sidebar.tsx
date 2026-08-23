import { Workflow } from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./navItems";

export function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] max-lg:hidden">
      <div className="flex h-14 items-center gap-2 border-b border-[var(--color-border-subtle)] px-4">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[var(--color-accent)]">
          <Workflow className="h-3.5 w-3.5 text-white" strokeWidth={2.5} />
        </div>
        <span className="text-sm font-semibold text-[var(--color-text-primary)]">Workflow Engine</span>
      </div>

      <nav className="flex flex-col gap-0.5 p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-[var(--color-surface-2)] text-[var(--color-text-primary)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text-primary)]",
              )
            }
          >
            <Icon className="h-4 w-4" strokeWidth={1.85} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
