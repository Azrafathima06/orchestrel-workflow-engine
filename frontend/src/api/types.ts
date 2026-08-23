/**
 * Types mirroring backend/app/api/schemas.py field-for-field, snake_case
 * preserved end to end. If a field is added or renamed in the backend
 * response schema, this file must change to match — there is no runtime
 * validation layer here, so this is the single contract.
 */

export type WorkflowStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "upstream_failed"
  | "cancelled";

export type AttemptStatus = "running" | "succeeded" | "failed";

export type TriggerType = "manual" | "scheduled" | "api";

export interface TaskCounts {
  total: number;
  pending: number;
  queued: number;
  running: number;
  retrying: number;
  succeeded: number;
  failed: number;
  upstream_failed: number;
  cancelled: number;
}

export interface RunSummary {
  id: string;
  definition_key: string;
  workflow_name: string;
  status: WorkflowStatus;
  trigger_type: TriggerType;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  retry_count: number;
  error: string | null;
  task_counts: TaskCounts;
}

export interface TaskRef {
  task_run_id: string;
  task_key: string;
  status: TaskStatus;
}

export interface WorkflowSummary {
  key: string;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  is_public: boolean;
  task_count: number;
  last_run: RunSummary | null;
  recent_success_count: number;
  recent_failure_count: number;
}

export interface WorkflowNode {
  task_key: string;
  handler: string;
  depends_on: string[];
  max_attempts: number;
  timeout_seconds: number;
}

export interface WorkflowEdge {
  source: string;
  target: string;
}

export interface WorkflowDetail {
  key: string;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  is_public: boolean;
  /** Raw spec document; shape not otherwise typed here. */
  spec: Record<string, unknown>;
  params_schema: Record<string, unknown>;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  recent_runs: RunSummary[];
}

export interface TriggerRunRequest {
  params: Record<string, unknown>;
}

export interface RunListResponse {
  items: RunSummary[];
  next_cursor: string | null;
}

export interface TaskRunSummary {
  id: string;
  task_key: string;
  handler: string;
  status: TaskStatus;
  depends_on: string[];
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  dispatch_count: number;
  worker_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  output: Record<string, unknown> | null;
  error_type: string | null;
  error_message: string | null;
}

export interface RunDetail {
  id: string;
  definition_key: string;
  workflow_name: string;
  status: WorkflowStatus;
  trigger_type: TriggerType;
  params: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error: string | null;
  retry_count: number;
  task_counts: TaskCounts;
  tasks: TaskRunSummary[];
  edges: WorkflowEdge[];
}

export interface AttemptDetail {
  attempt_number: number;
  status: AttemptStatus;
  worker_id: string;
  celery_task_id: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  traceback: string | null;
  logs: Record<string, unknown>[] | null;
}

export interface TaskRunDetail extends TaskRunSummary {
  params: Record<string, unknown>;
  timeout_seconds: number;
  dependencies: TaskRef[];
  dependents: TaskRef[];
  attempts: AttemptDetail[];
}

export interface RunCounts {
  total: number;
  succeeded: number;
  failed: number;
  running: number;
  cancelled: number;
}

export interface DailyCount {
  date: string;
  succeeded: number;
  failed: number;
}

export interface StatsOverview {
  runs: RunCounts;
  success_rate: number | null;
  avg_duration_ms: number | null;
  p95_duration_ms: number | null;
  retries: number;
  tasks_executed: number;
  recovered_tasks: number;
  daily: DailyCount[];
}

export type WorkerLiveness = "active" | "idle" | "stale";

export interface WorkerObservation {
  worker_id: string;
  first_seen_at: string;
  last_seen_at: string;
  attempts_total: number;
  attempts_1h: number;
  currently_running: number;
  liveness: WorkerLiveness;
}

export interface ComponentHealth {
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface ReadyResponse {
  database: ComponentHealth;
  broker: ComponentHealth;
  workers_observed_5m: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export interface RunListParams {
  status?: WorkflowStatus;
  workflow?: string;
  trigger?: TriggerType;
  limit?: number;
  cursor?: string;
}
