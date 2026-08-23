import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RetryCountdown } from "@/components/RetryCountdown";

describe("RetryCountdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the initial countdown from the server timestamp", () => {
    render(<RetryCountdown nextAttemptAt="2026-01-01T00:00:10.000Z" />);
    expect(screen.getByText("Next attempt in 10s")).toBeInTheDocument();
  });

  it("ticks down locally between server polls, without calling the server", () => {
    render(<RetryCountdown nextAttemptAt="2026-01-01T00:00:10.000Z" />);

    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(screen.getByText("Next attempt in 6s")).toBeInTheDocument();
  });

  it("recalibrates immediately when a fresh server timestamp arrives (a re-poll)", () => {
    const { rerender } = render(<RetryCountdown nextAttemptAt="2026-01-01T00:00:10.000Z" />);

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.getByText("Next attempt in 6s")).toBeInTheDocument();

    // Server reports a NEW next_attempt_at (e.g. the retry policy backed
    // off further) — the countdown must reflect the new value immediately,
    // not continue counting down from the stale one.
    rerender(<RetryCountdown nextAttemptAt="2026-01-01T00:00:20.000Z" />);
    expect(screen.getByText("Next attempt in 16s")).toBeInTheDocument();
  });

  it("reads 'any moment' once the countdown reaches zero, never a negative number", () => {
    render(<RetryCountdown nextAttemptAt="2026-01-01T00:00:02.000Z" />);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(screen.getByText("Next attempt in any moment")).toBeInTheDocument();
  });
});
