import dagre from "dagre";
import type { Edge } from "@xyflow/react";
import type { WorkflowEdge } from "@/api/types";
import { statusMeta } from "@/lib/status";

const NODE_WIDTH = 190;
const NODE_HEIGHT = 58;

export interface DagPosition {
  x: number;
  y: number;
}

/**
 * Compute a left-to-right dagre layout for a DAG. Returns only positions
 * and React Flow edges — the caller attaches whatever task data it has to
 * each node, so this stays a pure geometry function independent of the
 * task shape (used both for a live run's TaskRunSummary[] and a workflow
 * preview's WorkflowNode[]).
 *
 * Edge treatment is derived from the *target's* real status: an edge whose
 * target already succeeded reads as "completed", one whose target is
 * currently running/retrying reads as "active" (dashed, animated — the
 * only animation on the canvas), one whose target failed reads as
 * "failed", everything else (target not yet started) reads as "normal".
 * A preview with no statuses (all tasks default to pending) renders every
 * edge as normal, which is honest for a workflow that has never run.
 */
export function layoutDag(
  taskKeys: string[],
  edges: WorkflowEdge[],
  statusByKey: Record<string, string> = {},
): { positions: Record<string, DagPosition>; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 26, ranksep: 72 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const key of taskKeys) {
    g.setNode(key, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    if (g.hasNode(edge.source) && g.hasNode(edge.target)) {
      g.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(g);

  const positions: Record<string, DagPosition> = {};
  for (const key of taskKeys) {
    const pos = g.node(key);
    positions[key] = { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 };
  }

  const keySet = new Set(taskKeys);
  const rfEdges: Edge[] = edges
    .filter((edge) => keySet.has(edge.source) && keySet.has(edge.target))
    .map((edge) => {
      const targetStatus = statusByKey[edge.target] ?? "pending";
      const targetMeta = statusMeta(targetStatus);
      const isActive = targetStatus === "running" || targetStatus === "retrying";
      const isFailed = targetStatus === "failed" || targetStatus === "upstream_failed";
      const isCompleted = targetStatus === "succeeded";

      let stroke = "var(--color-border)";
      let strokeWidth = 1.25;
      if (isFailed) {
        stroke = "var(--color-status-failed)";
        strokeWidth = 1.5;
      } else if (isActive) {
        stroke = `var(${targetMeta.cssVar})`;
        strokeWidth = 1.5;
      } else if (isCompleted) {
        stroke = "var(--color-text-tertiary)";
        strokeWidth = 1.25;
      }

      return {
        id: `${edge.source}->${edge.target}`,
        source: edge.source,
        target: edge.target,
        animated: isActive,
        style: { stroke, strokeWidth, strokeDasharray: isActive ? "3 3" : undefined },
      };
    });

  return { positions, edges: rfEdges };
}
