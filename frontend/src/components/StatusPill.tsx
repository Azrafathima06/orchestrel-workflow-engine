import { cn } from "@/lib/utils";
import { statusMeta } from "@/lib/status";

interface StatusPillProps {
  status: string;
  size?: "sm" | "md";
  /** No background/border chrome — icon + colored text only. For dense
   *  tables and lists where a full badge on every row reads as noise;
   *  the status color and icon alone are still never ambiguous. */
  bare?: boolean;
  className?: string;
}

/**
 * The one place status is rendered. Every consumer gets an icon, a text
 * label, and a color together — status is never conveyed by color alone.
 */
export function StatusPill({ status, size = "md", bare = false, className }: StatusPillProps) {
  const meta = statusMeta(status);
  const Icon = meta.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-medium",
        !bare && "rounded-[var(--radius-sm)] border",
        !bare && meta.bgClass,
        !bare && meta.borderClass,
        meta.textClass,
        size === "md" && (bare ? "text-[13px]" : "px-2 py-1 text-xs"),
        size === "sm" && (bare ? "text-xs" : "px-1.5 py-0.5 text-[11px]"),
        className,
      )}
    >
      <Icon className={cn("h-3 w-3 shrink-0", meta.spin && "animate-spin")} strokeWidth={2.25} />
      {meta.label}
    </span>
  );
}
