import type { DailyCount } from "@/api/types";

/**
 * The backend only returns rows for days that actually had a run — sparse,
 * and honestly so. A 14-bar sparkline needs a bar for every day in the
 * window, so this fills the gaps with real zeros (never fabricated counts)
 * client-side, keyed by the same YYYY-MM-DD the API already uses.
 */
export function fillDailyRange(daily: DailyCount[], days = 14, today = new Date()): DailyCount[] {
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const filled: DailyCount[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    filled.push(byDate.get(key) ?? { date: key, succeeded: 0, failed: 0 });
  }
  return filled;
}

/**
 * Fourteen thin bars, one per day, height proportional to that day's run
 * volume and hue mixed by its real success ratio. A compact, honest stand-in
 * for a chart — no decorative curve, no fabricated smoothing.
 */
export function Sparkline({ daily }: { daily: DailyCount[] }) {
  if (daily.length === 0) return null;

  const filled = fillDailyRange(daily);
  const max = Math.max(...filled.map((d) => d.succeeded + d.failed), 1);

  return (
    <div className="flex h-8 items-end gap-[3px]" role="img" aria-label="Runs over the last 14 days">
      {filled.map((d) => {
        const total = d.succeeded + d.failed;
        const heightPct = total === 0 ? 12 : Math.max(24, (total / max) * 100);
        const successRatio = total === 0 ? 0 : d.succeeded / total;
        const color =
          total === 0
            ? "var(--color-border)"
            : successRatio >= 0.8
              ? "var(--color-status-succeeded)"
              : successRatio >= 0.4
                ? "var(--color-status-retrying)"
                : "var(--color-status-failed)";

        return (
          <div
            key={d.date}
            title={`${d.date}: ${d.succeeded} succeeded, ${d.failed} failed`}
            className="w-[5px] rounded-full opacity-70 transition-opacity hover:opacity-100"
            style={{ height: `${heightPct}%`, backgroundColor: color }}
          />
        );
      })}
    </div>
  );
}
