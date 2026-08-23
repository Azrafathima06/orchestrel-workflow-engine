import { ChevronRight, Menu } from "lucide-react";
import { Fragment, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useReady } from "@/api/queries";
import { Sheet } from "@/components/ui/Sheet";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./navItems";

function useBreadcrumbs(): { label: string; to: string }[] {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);

  if (segments.length === 0) return [{ label: "Overview", to: "/" }];

  const crumbs: { label: string; to: string }[] = [];
  let path = "";
  for (const segment of segments) {
    path += `/${segment}`;
    const label = segment.length > 12 ? `${segment.slice(0, 8)}…` : segment;
    crumbs.push({ label: label.charAt(0).toUpperCase() + label.slice(1), to: path });
  }
  return crumbs;
}

function ReadinessDot() {
  const { data, isError } = useReady();

  const dbOk = data?.database.ok ?? false;
  const brokerOk = data?.broker.ok ?? false;
  const allOk = dbOk && brokerOk;

  const label = isError
    ? "Backend unreachable"
    : !data
      ? "Checking backend…"
      : allOk
        ? "All systems operational"
        : `${!dbOk ? "Database unreachable. " : ""}${!brokerOk ? "Broker unreachable." : ""}`;

  return (
    <Tooltip content={label}>
      <span className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)] px-2.5 py-1 text-xs">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            allOk ? "bg-[var(--color-status-succeeded)]" : "bg-[var(--color-status-failed)]",
          )}
        />
        <span className="text-[var(--color-text-secondary)]">
          {allOk ? "Operational" : "Degraded"}
        </span>
      </span>
    </Tooltip>
  );
}

/** Nav drawer for viewports where the persistent Sidebar is hidden (< lg). */
function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
        className="rounded-md p-1.5 text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] lg:hidden"
      >
        <Menu className="h-4.5 w-4.5" />
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Navigate">
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
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
      </Sheet>
    </>
  );
}

export function Topbar() {
  const crumbs = useBreadcrumbs();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-0)] px-4">
      <div className="flex min-w-0 items-center gap-2">
        <MobileNav />
        <nav className="flex min-w-0 items-center gap-1.5 overflow-hidden text-sm text-[var(--color-text-tertiary)]">
          {crumbs.map((crumb, i) => (
            <Fragment key={crumb.to}>
              {i > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
              <Link
                to={crumb.to}
                className={cn(
                  "truncate font-mono",
                  i === crumbs.length - 1
                    ? "text-[var(--color-text-primary)]"
                    : "hover:text-[var(--color-text-secondary)]",
                )}
              >
                {crumb.label}
              </Link>
            </Fragment>
          ))}
        </nav>
      </div>
      <ReadinessDot />
    </header>
  );
}
