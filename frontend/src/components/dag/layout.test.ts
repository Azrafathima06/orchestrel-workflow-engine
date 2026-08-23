import { describe, expect, it } from "vitest";
import type { WorkflowEdge } from "@/api/types";
import { layoutDag } from "./layout";

describe("layoutDag", () => {
  it("positions every task key exactly once", () => {
    const keys = ["extract", "transform", "validate", "load"];
    const edges: WorkflowEdge[] = [
      { source: "extract", target: "transform" },
      { source: "transform", target: "validate" },
      { source: "validate", target: "load" },
    ];

    const { positions } = layoutDag(keys, edges);

    expect(Object.keys(positions).sort()).toEqual(keys.sort());
  });

  it("lays out a sequential chain left-to-right in dependency order", () => {
    const keys = ["a", "b", "c"];
    const edges: WorkflowEdge[] = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
    ];

    const { positions } = layoutDag(keys, edges);

    expect(positions.a.x).toBeLessThan(positions.b.x);
    expect(positions.b.x).toBeLessThan(positions.c.x);
  });

  it("places fan-out siblings at the same rank, after their shared source", () => {
    const keys = ["split", "shard_0", "shard_1", "shard_2", "merge"];
    const edges: WorkflowEdge[] = [
      { source: "split", target: "shard_0" },
      { source: "split", target: "shard_1" },
      { source: "split", target: "shard_2" },
      { source: "shard_0", target: "merge" },
      { source: "shard_1", target: "merge" },
      { source: "shard_2", target: "merge" },
    ];

    const { positions } = layoutDag(keys, edges);

    // All three shards share a rank (same x), strictly after split and
    // strictly before merge.
    expect(positions.shard_0.x).toBe(positions.shard_1.x);
    expect(positions.shard_1.x).toBe(positions.shard_2.x);
    expect(positions.split.x).toBeLessThan(positions.shard_0.x);
    expect(positions.shard_0.x).toBeLessThan(positions.merge.x);

    // And they must not overlap vertically.
    const ys = [positions.shard_0.y, positions.shard_1.y, positions.shard_2.y];
    expect(new Set(ys).size).toBe(3);
  });

  it("produces one React Flow edge per input edge, referencing the right endpoints", () => {
    const keys = ["a", "b"];
    const edges: WorkflowEdge[] = [{ source: "a", target: "b" }];

    const { edges: rfEdges } = layoutDag(keys, edges);

    expect(rfEdges).toHaveLength(1);
    expect(rfEdges[0].source).toBe("a");
    expect(rfEdges[0].target).toBe("b");
  });

  it("marks an edge animated only when its target's real status is running/retrying", () => {
    const keys = ["a", "b", "c"];
    const edges: WorkflowEdge[] = [
      { source: "a", target: "b" },
      { source: "a", target: "c" },
    ];

    const { edges: rfEdges } = layoutDag(keys, edges, { b: "running", c: "pending" });

    const toB = rfEdges.find((e) => e.target === "b");
    const toC = rfEdges.find((e) => e.target === "c");
    expect(toB?.animated).toBe(true);
    expect(toC?.animated).toBe(false);
  });

  it("gives a failed target's edge the failed color, not the active color", () => {
    const keys = ["a", "b"];
    const edges: WorkflowEdge[] = [{ source: "a", target: "b" }];

    const { edges: rfEdges } = layoutDag(keys, edges, { b: "failed" });

    expect(rfEdges[0].animated).toBe(false);
    expect(rfEdges[0].style?.stroke).toBe("var(--color-status-failed)");
  });

  it("silently drops an edge referencing an unknown task rather than crashing", () => {
    const keys = ["a"];
    const edges: WorkflowEdge[] = [{ source: "a", target: "ghost" }];

    expect(() => layoutDag(keys, edges)).not.toThrow();
    const { edges: rfEdges } = layoutDag(keys, edges);
    expect(rfEdges).toHaveLength(0);
  });
});
