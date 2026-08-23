import { describe, expect, it } from "vitest";
import type { TaskRunSummary } from "@/api/types";
import { orderTasksForStrip } from "@/components/ExecutionStrip";

function task(overrides: Partial<TaskRunSummary>): TaskRunSummary {
  return {
    id: overrides.task_key ?? "t",
    task_key: "t",
    handler: "noop",
    status: "pending",
    depends_on: [],
    attempt_count: 0,
    max_attempts: 1,
    next_attempt_at: null,
    dispatch_count: 0,
    worker_id: null,
    started_at: null,
    finished_at: null,
    duration_ms: null,
    output: null,
    error_type: null,
    error_message: null,
    ...overrides,
  };
}

describe("orderTasksForStrip", () => {
  it("orders started tasks by real start time, earliest first", () => {
    const tasks = [
      task({ task_key: "b", started_at: "2026-01-01T00:00:02.000Z" }),
      task({ task_key: "a", started_at: "2026-01-01T00:00:01.000Z" }),
    ];
    expect(orderTasksForStrip(tasks).map((t) => t.task_key)).toEqual(["a", "b"]);
  });

  it("places never-started tasks after every started task", () => {
    const tasks = [
      task({ task_key: "pending_task" }),
      task({ task_key: "ran", started_at: "2026-01-01T00:00:01.000Z" }),
    ];
    expect(orderTasksForStrip(tasks).map((t) => t.task_key)).toEqual(["ran", "pending_task"]);
  });

  it("breaks ties (including simultaneous parallel starts) by task_key", () => {
    const sameInstant = "2026-01-01T00:00:00.000Z";
    const tasks = [
      task({ task_key: "shard_2", started_at: sameInstant }),
      task({ task_key: "shard_0", started_at: sameInstant }),
      task({ task_key: "shard_1", started_at: sameInstant }),
    ];
    expect(orderTasksForStrip(tasks).map((t) => t.task_key)).toEqual([
      "shard_0",
      "shard_1",
      "shard_2",
    ]);
  });

  it("does not mutate the input array", () => {
    const tasks = [task({ task_key: "b" }), task({ task_key: "a" })];
    const original = [...tasks];
    orderTasksForStrip(tasks);
    expect(tasks).toEqual(original);
  });
});
