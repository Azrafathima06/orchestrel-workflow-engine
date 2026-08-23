import { describe, expect, it } from "vitest";
import type { DailyCount } from "@/api/types";
import { fillDailyRange } from "../Sparkline";

describe("fillDailyRange", () => {
  it("returns exactly `days` entries ending on the reference date", () => {
    const today = new Date(Date.UTC(2026, 7, 23));
    const filled = fillDailyRange([], 14, today);

    expect(filled).toHaveLength(14);
    expect(filled[13].date).toBe("2026-08-23");
    expect(filled[0].date).toBe("2026-08-10");
  });

  it("preserves real counts for days the backend reported and zero-fills the rest", () => {
    const today = new Date(Date.UTC(2026, 7, 23));
    const daily: DailyCount[] = [{ date: "2026-08-23", succeeded: 3, failed: 1 }];

    const filled = fillDailyRange(daily, 14, today);

    expect(filled[13]).toEqual({ date: "2026-08-23", succeeded: 3, failed: 1 });
    expect(filled[0]).toEqual({ date: "2026-08-10", succeeded: 0, failed: 0 });
    expect(filled.slice(0, 13).every((d) => d.succeeded === 0 && d.failed === 0)).toBe(true);
  });
});
