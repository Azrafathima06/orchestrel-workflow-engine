import { NavLink } from "react-router-dom";
import { useHealth, useReady } from "@/api/queries";
import { OrchestrelMark } from "@/components/OrchestrelMark";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./navItems";

function SystemFooter() {
  const { data: ready } = useReady();
  const { data: health } = useHealth();

  const allOk = !!ready && ready.database.ok && ready.broker.ok;

  return (
    <div className="border-t border-[var(--color-border-subtle)] px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-tertiary)]">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            allOk ? "bg-[var(--color-status-succeeded)]" : "bg-[var(--color-status-failed)]",
          )}
        />
        {ready ? (allOk ? "All systems operational" : "Degraded") : "Checking…"}
      </div>
      {health?.version && (
        <div className="mt-1 font-mono text-[10.5px] text-[var(--color-text-tertiary)]">
          v{health.version}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] max-lg:hidden">
      <div className="flex h-14 items-center gap-2.5 border-b border-[var(--color-border-subtle)] px-4">
        <OrchestrelMark />
        <span className="text-[15px] font-semibold tracking-tight text-[var(--color-text-primary)]">
          Orchestrel
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-px p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "group relative flex items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 py-[7px] text-[13px] font-medium transition-colors duration-150",
                isActive
                  ? "text-[var(--color-text-primary)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text-primary)]",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={cn(
                    "absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-full bg-[var(--color-accent)] transition-opacity duration-150",
                    isActive ? "opacity-100" : "opacity-0",
                  )}
                />
                <Icon
                  className={cn(
                    "h-[15px] w-[15px] shrink-0",
                    isActive
                      ? "text-[var(--color-text-primary)]"
                      : "text-[var(--color-text-tertiary)] group-hover:text-[var(--color-text-secondary)]",
                  )}
                  strokeWidth={1.85}
                />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <SystemFooter />
    </aside>
  );
}
