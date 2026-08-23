import { Loader2, Workflow, WifiOff } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { apiUrl } from "@/api/client";
import { Button } from "@/components/ui/Button";

const RETRY_SCHEDULE_MS = [2000, 3000, 5000, 8000, 12000];
const STEADY_RETRY_MS = 10000;
const UNREACHABLE_AFTER_MS = 120_000;
const PING_TIMEOUT_MS = 4000;

type GateState = "checking" | "waking" | "ready" | "unreachable";

async function pingHealth(timeoutMs: number): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl("/health"), { signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

export function BackendGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>("checking");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const start = Date.now();
    let attemptIndex = 0;
    let retryTimer: number | undefined;

    const elapsedTimer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
    }, 1000);

    async function attempt() {
      if (cancelled) return;
      const ok = await pingHealth(PING_TIMEOUT_MS);
      if (cancelled) return;

      if (ok) {
        setState("ready");
        window.clearInterval(elapsedTimer);
        return;
      }

      const elapsed = Date.now() - start;
      if (elapsed >= UNREACHABLE_AFTER_MS) {
        setState("unreachable");
        window.clearInterval(elapsedTimer);
        return;
      }

      // Only escalate to the visible "waking" UI once the very first,
      // fast attempt has already failed — a warm backend never reaches
      // this line.
      setState("waking");
      const delay =
        attemptIndex < RETRY_SCHEDULE_MS.length ? RETRY_SCHEDULE_MS[attemptIndex] : STEADY_RETRY_MS;
      attemptIndex += 1;
      retryTimer = window.setTimeout(attempt, delay);
    }

    attempt();

    return () => {
      cancelled = true;
      window.clearInterval(elapsedTimer);
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [retryKey]);

  if (state === "ready") return <>{children}</>;

  if (state === "unreachable") {
    return (
      <GateScreen>
        <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--color-status-failed)]/25 bg-[var(--color-status-failed)]/10">
          <WifiOff className="h-5 w-5 text-[var(--color-status-failed)]" strokeWidth={1.75} />
        </div>
        <p className="text-sm font-medium text-[var(--color-text-primary)]">
          Couldn't reach the API.
        </p>
        <p className="max-w-xs text-sm text-[var(--color-text-tertiary)]">
          We tried for {Math.floor(UNREACHABLE_AFTER_MS / 1000)} seconds without success.
        </p>
        <Button
          variant="primary"
          size="sm"
          onClick={() => {
            setState("checking");
            setElapsedSeconds(0);
            setRetryKey((k) => k + 1);
          }}
        >
          Try again
        </Button>
      </GateScreen>
    );
  }

  if (state === "checking" && elapsedSeconds === 0) {
    // Sub-second window before the first ping resolves — render nothing
    // rather than a flash of loading UI a warm backend would never need.
    return null;
  }

  // "waking" — and "checking" past the immediate threshold, in case a slow
  // first response is still pending.
  const progressPct = Math.min(95, (elapsedSeconds * 1000 * 100) / 60_000);

  return (
    <GateScreen>
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)]">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-accent)]" strokeWidth={1.75} />
      </div>
      <p className="text-sm font-medium text-[var(--color-text-primary)]">
        Starting workflow engine…
      </p>
      <p className="max-w-xs text-sm text-[var(--color-text-tertiary)]">
        The API runs on free hosting and may take a short time to wake after inactivity.
      </p>
      <div className="w-56">
        <div className="h-1 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
          <div
            className="h-full rounded-full bg-[var(--color-accent)] transition-all duration-700 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <p className="mt-1.5 text-center text-xs tabular-nums text-[var(--color-text-tertiary)]">
          waking · {elapsedSeconds}s
        </p>
      </div>
    </GateScreen>
  );
}

function GateScreen({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 bg-[var(--color-surface-0)] px-6 text-center">
      <div className="mb-2 flex flex-col items-center gap-1 text-[var(--color-text-tertiary)]">
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4" strokeWidth={1.75} />
          <span className="text-xs font-medium">Orchestrel</span>
        </div>
        <span className="text-[10.5px] text-[var(--color-text-tertiary)]">
          Distributed Workflow Control Plane
        </span>
      </div>
      {children}
    </div>
  );
}
