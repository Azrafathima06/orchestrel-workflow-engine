import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";
import type {
  ReadyResponse,
  RunDetail,
  RunListParams,
  RunListResponse,
  StatsOverview,
  TaskRunDetail,
  TriggerRunRequest,
  WorkerObservation,
  WorkflowDetail,
  WorkflowSummary,
} from "./types";
import { isNonTerminal } from "@/lib/status";

// How often the Overview status strip re-checks readiness. Independent of
// run-detail polling, which is driven by whether a specific run is live.
const READY_POLL_MS = 20_000;
const RUN_POLL_MS = 2_000;

export function useReady() {
  return useQuery({
    queryKey: ["ready"],
    queryFn: () => apiRequest<ReadyResponse>("/ready"),
    refetchInterval: READY_POLL_MS,
    retry: 1,
  });
}

/** The real running app_version, for the sidebar footer — never invented. */
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiRequest<{ status: string; version: string }>("/health"),
    staleTime: Number.POSITIVE_INFINITY, // the version cannot change mid-session
    retry: 1,
  });
}

export function useWorkflows() {
  return useQuery({
    queryKey: ["workflows"],
    queryFn: () => apiRequest<WorkflowSummary[]>("/api/v1/workflows"),
  });
}

export function useWorkflow(key: string | undefined) {
  return useQuery({
    queryKey: ["workflows", key],
    queryFn: () => apiRequest<WorkflowDetail>(`/api/v1/workflows/${key}`),
    enabled: !!key,
  });
}

export function useTriggerRun(key: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TriggerRunRequest) =>
      apiRequest<RunDetail>(`/api/v1/workflows/${key}/runs`, { method: "POST", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useRuns(params: Omit<RunListParams, "cursor">) {
  return useInfiniteQuery({
    queryKey: ["runs", params],
    queryFn: ({ pageParam }) =>
      apiRequest<RunListResponse>("/api/v1/runs", {
        params: { ...params, cursor: pageParam },
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["runs", "detail", runId],
    queryFn: () => apiRequest<RunDetail>(`/api/v1/runs/${runId}`),
    enabled: !!runId,
    // Poll only while the run is genuinely still moving; stop the instant
    // the server reports a terminal status. refetchIntervalInBackground
    // defaults to false, so polling also pauses while the tab is hidden.
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return RUN_POLL_MS;
      return isNonTerminal(data.status) ? RUN_POLL_MS : false;
    },
  });
}

export function useTaskDetail(runId: string | undefined, taskRunId: string | undefined) {
  return useQuery({
    queryKey: ["runs", "detail", runId, "tasks", taskRunId],
    queryFn: () =>
      apiRequest<TaskRunDetail>(`/api/v1/runs/${runId}/tasks/${taskRunId}`),
    enabled: !!runId && !!taskRunId,
    // Piggybacks on the run-detail poll for freshness; a short-lived
    // independent poll keeps the inspector panel in sync too.
    refetchInterval: RUN_POLL_MS,
  });
}

export function useStatsOverview() {
  return useQuery({
    queryKey: ["stats", "overview"],
    queryFn: () => apiRequest<StatsOverview>("/api/v1/stats/overview"),
    refetchInterval: READY_POLL_MS,
  });
}

export function useWorkers() {
  return useQuery({
    queryKey: ["workers"],
    queryFn: () => apiRequest<WorkerObservation[]>("/api/v1/workers"),
    refetchInterval: READY_POLL_MS,
  });
}
