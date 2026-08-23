import type { ApiErrorBody } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;
  details: unknown;

  constructor(message: string, code: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  params?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
}

/**
 * The single place an HTTP request leaves this app. No component or hook
 * calls fetch() directly — everything goes through here, so the base URL,
 * error shape, and JSON handling exist in exactly one place.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(path, BASE_URL);
  if (options.params) {
    for (const [key, value] of Object.entries(options.params)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url, {
    method: options.method ?? "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = await response.json();
    } catch {
      // Response wasn't JSON (e.g. a proxy error page) — fall through to
      // the generic message below.
    }
    throw new ApiError(
      body?.error?.message ?? `request failed with status ${response.status}`,
      body?.error?.code ?? "unknown_error",
      response.status,
      body?.error?.details,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export function apiUrl(path: string): string {
  return new URL(path, BASE_URL).toString();
}
