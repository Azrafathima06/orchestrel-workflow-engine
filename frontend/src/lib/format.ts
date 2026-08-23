/** Formatting helpers, centralized so no page hand-rolls its own duration/id math. */

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(totalSeconds < 10 ? 2 : 1)}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Live elapsed duration for a still-running item: now - startedAt. */
export function formatElapsed(startedAt: string | null | undefined): string {
  if (!startedAt) return "—";
  const elapsed = Date.now() - new Date(startedAt).getTime();
  return formatDuration(Math.max(0, elapsed));
}

export function formatShortId(id: string): string {
  return id.slice(0, 8);
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const diffSec = Math.round(diffMs / 1000);

  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Seconds remaining until `iso`, floored at 0. Used by RetryCountdown. */
export function secondsUntil(iso: string | null | undefined): number {
  if (!iso) return 0;
  const target = new Date(iso).getTime();
  return Math.max(0, Math.round((target - Date.now()) / 1000));
}

export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "any moment";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}
