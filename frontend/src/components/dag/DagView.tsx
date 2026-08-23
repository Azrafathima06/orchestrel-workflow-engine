import { Background, BackgroundVariant, Controls, ReactFlow, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { TaskRunSummary, WorkflowEdge } from "@/api/types";
import { DagNode, type DagNodeData } from "./DagNode";
import { layoutDag } from "./layout";

const nodeTypes = { task: DagNode };

interface DagViewProps {
  tasks: TaskRunSummary[];
  edges: WorkflowEdge[];
  selectedTaskKey?: string | null;
  onSelectTask?: (taskKey: string) => void;
}

export function DagView({ tasks, edges, selectedTaskKey, onSelectTask }: DagViewProps) {
  const { nodes, flowEdges } = useMemo(() => {
    const activeTargets = new Set(
      tasks.filter((t) => t.status === "running" || t.status === "retrying").map((t) => t.task_key),
    );
    const { positions, edges: rfEdges } = layoutDag(
      tasks.map((t) => t.task_key),
      edges,
      activeTargets,
    );

    const rfNodes: Node<DagNodeData>[] = tasks.map((task) => ({
      id: task.task_key,
      type: "task",
      position: positions[task.task_key] ?? { x: 0, y: 0 },
      data: { task, selected: task.task_key === selectedTaskKey },
      draggable: false,
    }));

    return { nodes: rfNodes, flowEdges: rfEdges };
  }, [tasks, edges, selectedTaskKey]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectTask?.(node.id)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
        elementsSelectable
        panOnScroll
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--color-border-subtle)" />
        <Controls showInteractive={false} className="!shadow-none [&>button]:!border-[var(--color-border)] [&>button]:!bg-[var(--color-surface-1)] [&>button]:!fill-[var(--color-text-secondary)]" />
      </ReactFlow>
    </div>
  );
}
