import { useEffect, useState } from "react";
import { formatCountdown, secondsUntil } from "@/lib/format";

interface RetryCountdownProps {
  nextAttemptAt: string;
}

/**
 * Display-only countdown to a server-provided timestamp. It never triggers
 * anything — the actual retry release is decided entirely server-side by
 * comparing `next_attempt_at` against the database clock. Each poll of the
 * parent run/task refreshes `nextAttemptAt`, which recalibrates this
 * countdown against reality; the local ticking between polls is purely
 * cosmetic.
 */
export function RetryCountdown({ nextAttemptAt }: RetryCountdownProps) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const seconds = secondsUntil(nextAttemptAt);

  return (
    <span className="tabular-nums">
      Next attempt in {formatCountdown(seconds)}
    </span>
  );
}
