import dagre from "dagre";
import type { Edge } from "@xyflow/react";
import type { WorkflowEdge } from "@/api/types";

const NODE_WIDTH = 200;
const NODE_HEIGHT = 68;

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
 */
export function layoutDag(
  taskKeys: string[],
  edges: WorkflowEdge[],
  activeTargets: Set<string> = new Set(),
): { positions: Record<string, DagPosition>; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 28, ranksep: 64 });
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
    .map((edge) => ({
      id: `${edge.source}->${edge.target}`,
      source: edge.source,
      target: edge.target,
      animated: activeTargets.has(edge.target),
      style: { stroke: "var(--color-border)", strokeWidth: 1.5 },
    }));

  return { positions, edges: rfEdges };
}
