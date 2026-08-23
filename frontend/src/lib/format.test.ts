import { describe, expect, it, vi } from "vitest";
import { formatCountdown, formatDuration, formatShortId, secondsUntil } from "./format";

describe("formatDuration", () => {
  it("renders sub-second durations in milliseconds", () => {
    expect(formatDuration(4)).toBe("4ms");
    expect(formatDuration(999)).toBe("999ms");
  });

  it("renders sub-minute durations in seconds", () => {
    expect(formatDuration(1500)).toBe("1.50s");
    expect(formatDuration(12_340)).toBe("12.3s");
  });

  it("renders minute-scale durations as m/s", () => {
    expect(formatDuration(65_000)).toBe("1m 5s");
    expect(formatDuration(125_000)).toBe("2m 5s");
  });

  it("renders hour-scale durations as h/m", () => {
    expect(formatDuration(3_700_000)).toBe("1h 1m");
  });

  it("renders null/undefined as an em dash", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });
});

describe("formatShortId", () => {
  it("truncates a UUID to its first 8 characters", () => {
    expect(formatShortId("5b6b9e96-c087-4c33-8cd0-abb124958ec8")).toBe("5b6b9e96");
  });
});

describe("secondsUntil / formatCountdown", () => {
  it("computes remaining seconds against the system clock, floored at zero", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));

    expect(secondsUntil("2026-01-01T00:00:05.000Z")).toBe(5);
    expect(secondsUntil("2025-12-31T23:59:55.000Z")).toBe(0); // already past

    vi.useRealTimers();
  });

  it("formats a countdown in seconds under a minute", () => {
    expect(formatCountdown(45)).toBe("45s");
  });

  it("formats a countdown over a minute as m/s", () => {
    expect(formatCountdown(90)).toBe("1m 30s");
  });

  it("formats zero/negative as 'any moment' rather than '0s'", () => {
    expect(formatCountdown(0)).toBe("any moment");
  });
});
