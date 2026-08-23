import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleDot,
  Clock,
  type LucideIcon,
  RotateCw,
  XCircle,
} from "lucide-react";

/**
 * Every status this app renders — workflow runs, tasks, and attempts share
 * a single status vocabulary here so no component invents its own colors.
 * Status is NEVER color-only: every consumer of this map must also render
 * `icon` and `label`.
 */
export type Status =
  | "pending"
  | "queued"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "upstream_failed"
  | "cancelled";

export interface StatusMeta {
  label: string;
  icon: LucideIcon;
  /** Tailwind text/border/bg utility classes built from the CSS status tokens. */
  textClass: string;
  bgClass: string;
  borderClass: string;
  /** The raw CSS custom property, for contexts that need a literal color
   *  value (canvas/SVG) rather than a Tailwind arbitrary-value class. */
  cssVar: string;
  /** True while the status represents work that may still change. */
  isActive: boolean;
  /** True once the status can never change again. */
  isTerminal: boolean;
  /** True once handler code has actually run for this status — the FAILED
   *  vs UPSTREAM_FAILED distinction in one flag, reused anywhere that needs
   *  to distinguish "ran" from "never ran" (e.g. the execution strip). */
  hasExecuted: boolean;
  spin?: boolean;
}

export const STATUS_META: Record<Status, StatusMeta> = {
  pending: {
    label: "Pending",
    icon: Clock,
    textClass: "text-[var(--color-status-pending)]",
    bgClass: "bg-[var(--color-status-pending)]/10",
    borderClass: "border-[var(--color-status-pending)]/25",
    cssVar: "--color-status-pending",
    isActive: false,
    isTerminal: false,
    hasExecuted: false,
  },
  queued: {
    label: "Queued",
    icon: CircleDashed,
    textClass: "text-[var(--color-status-queued)]",
    bgClass: "bg-[var(--color-status-queued)]/10",
    borderClass: "border-[var(--color-status-queued)]/25",
    cssVar: "--color-status-queued",
    isActive: true,
    isTerminal: false,
    hasExecuted: false,
  },
  running: {
    label: "Running",
    icon: CircleDot,
    textClass: "text-[var(--color-status-running)]",
    bgClass: "bg-[var(--color-status-running)]/10",
    borderClass: "border-[var(--color-status-running)]/30",
    cssVar: "--color-status-running",
    isActive: true,
    isTerminal: false,
    hasExecuted: true,
  },
  retrying: {
    label: "Retrying",
    icon: RotateCw,
    textClass: "text-[var(--color-status-retrying)]",
    bgClass: "bg-[var(--color-status-retrying)]/10",
    borderClass: "border-[var(--color-status-retrying)]/30",
    cssVar: "--color-status-retrying",
    isActive: true,
    isTerminal: false,
    hasExecuted: true,
    spin: true,
  },
  succeeded: {
    label: "Succeeded",
    icon: CheckCircle2,
    textClass: "text-[var(--color-status-succeeded)]",
    bgClass: "bg-[var(--color-status-succeeded)]/10",
    borderClass: "border-[var(--color-status-succeeded)]/25",
    cssVar: "--color-status-succeeded",
    isActive: false,
    isTerminal: true,
    hasExecuted: true,
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    textClass: "text-[var(--color-status-failed)]",
    bgClass: "bg-[var(--color-status-failed)]/10",
    borderClass: "border-[var(--color-status-failed)]/25",
    cssVar: "--color-status-failed",
    isActive: false,
    isTerminal: true,
    hasExecuted: true,
  },
  upstream_failed: {
    label: "Upstream failed",
    icon: AlertTriangle,
    textClass: "text-[var(--color-status-upstream-failed)]",
    bgClass: "bg-[var(--color-status-upstream-failed)]/10",
    borderClass: "border-[var(--color-status-upstream-failed)]/25",
    cssVar: "--color-status-upstream-failed",
    isActive: false,
    isTerminal: true,
    hasExecuted: false,
  },
  cancelled: {
    label: "Cancelled",
    icon: Ban,
    textClass: "text-[var(--color-status-cancelled)]",
    bgClass: "bg-[var(--color-status-cancelled)]/10",
    borderClass: "border-[var(--color-status-cancelled)]/25",
    cssVar: "--color-status-cancelled",
    isActive: false,
    isTerminal: true,
    hasExecuted: false,
  },
};

export function statusMeta(status: string): StatusMeta {
  return STATUS_META[status as Status] ?? STATUS_META.pending;
}

/** A run/task is non-terminal (worth polling) if its status can still change. */
export function isNonTerminal(status: string): boolean {
  return !statusMeta(status).isTerminal;
}
