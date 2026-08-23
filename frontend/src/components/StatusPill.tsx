import { cn } from "@/lib/utils";
import { statusMeta } from "@/lib/status";

interface StatusPillProps {
  status: string;
  size?: "sm" | "md";
  className?: string;
}

/**
 * The one place status is rendered. Every consumer gets an icon, a text
 * label, and a color together — status is never conveyed by color alone.
 */
export function StatusPill({ status, size = "md", className }: StatusPillProps) {
  const meta = statusMeta(status);
  const Icon = meta.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        meta.textClass,
        meta.bgClass,
        meta.borderClass,
        size === "md" && "px-2.5 py-1 text-xs",
        size === "sm" && "px-1.5 py-0.5 text-[11px]",
        className,
      )}
    >
      <Icon className={cn("h-3 w-3", meta.spin && "animate-spin")} strokeWidth={2.25} />
      {meta.label}
    </span>
  );
}
