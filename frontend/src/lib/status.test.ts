import { describe, expect, it } from "vitest";
import { isNonTerminal, STATUS_META, statusMeta } from "./status";

describe("statusMeta", () => {
  it("returns a distinct entry for every task/run status the backend can send", () => {
    const statuses = [
      "pending",
      "queued",
      "running",
      "retrying",
      "succeeded",
      "failed",
      "upstream_failed",
      "cancelled",
    ];
    for (const status of statuses) {
      const meta = statusMeta(status);
      expect(meta.label).toBeTruthy();
      expect(meta.icon).toBeTruthy();
    }
  });

  it("every status has a distinct label — no two statuses read identically", () => {
    const labels = Object.values(STATUS_META).map((m) => m.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("falls back to pending for an unrecognized status rather than throwing", () => {
    expect(() => statusMeta("something_new")).not.toThrow();
    expect(statusMeta("something_new")).toBe(STATUS_META.pending);
  });
});

describe("isNonTerminal", () => {
  it("treats succeeded/failed/upstream_failed/cancelled as terminal", () => {
    expect(isNonTerminal("succeeded")).toBe(false);
    expect(isNonTerminal("failed")).toBe(false);
    expect(isNonTerminal("upstream_failed")).toBe(false);
    expect(isNonTerminal("cancelled")).toBe(false);
  });

  it("treats pending/queued/running/retrying as non-terminal (worth polling)", () => {
    expect(isNonTerminal("pending")).toBe(true);
    expect(isNonTerminal("queued")).toBe(true);
    expect(isNonTerminal("running")).toBe(true);
    expect(isNonTerminal("retrying")).toBe(true);
  });
});
