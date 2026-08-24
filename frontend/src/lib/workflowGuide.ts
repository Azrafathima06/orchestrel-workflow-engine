import {
  GitBranch,
  HeartPulse,
  RotateCw,
  ShieldAlert,
  Split,
  type LucideIcon,
} from "lucide-react";

/**
 * Presentation-layer copy for the seeded demo workflows.
 *
 * The API already returns each workflow's full `description`, but those are
 * written for someone reading the engine's own docs — several sentences,
 * naming internals like leases and sweepers. A first-time visitor landing on
 * the dashboard needs one line telling them which engine behaviour a given
 * workflow is there to prove, so they can pick one and watch it happen.
 *
 * Anything not listed here falls back to the API description, so a new
 * seeded workflow still renders correctly without touching the frontend.
 */
export interface WorkflowGuide {
  /** Two or three words naming the behaviour under test. */
  headline: string;
  /** One sentence, plain language, describing what you will actually see. */
  blurb: string;
  icon: LucideIcon;
  /** CSS custom property used to tint the card, so the grid reads as five
   *  distinct behaviours rather than five identical tiles. */
  accentVar: string;
  /** Display order. Deliberately not alphabetical: the two workflows that
   *  are most interesting to watch execute come first, and the one that
   *  cannot be triggered from the public demo comes last, so a visitor is
   *  never offered a dead end as their first option. */
  order: number;
}

export const WORKFLOW_GUIDES: Record<string, WorkflowGuide> = {
  sequential_etl: {
    headline: "Dependency ordering",
    blurb:
      "Four stages in a straight line. Each one starts only after the previous has succeeded, and checks the output it was handed.",
    icon: GitBranch,
    accentVar: "--color-status-queued",
    order: 4,
  },
  fanout_join: {
    headline: "Parallel execution",
    blurb:
      "One task makes four shards runnable at once. Independent workers take them concurrently, then a join waits for all four before merging.",
    icon: Split,
    accentVar: "--color-status-running",
    order: 2,
  },
  retry_backoff: {
    headline: "Retries and backoff",
    blurb:
      "The middle stage fails on purpose, then retries on a persisted exponential-backoff schedule until it succeeds.",
    icon: RotateCw,
    accentVar: "--color-status-retrying",
    order: 3,
  },
  failure_isolation: {
    headline: "Failure isolation",
    blurb:
      "One branch fails permanently. Only its own descendants are skipped — the parallel branch still runs to completion.",
    icon: ShieldAlert,
    accentVar: "--color-status-failed",
    order: 1,
  },
  crash_recovery: {
    headline: "Worker-loss recovery",
    blurb:
      "Kill a worker mid-task: its lease expires, the sweeper reclaims the attempt, and a surviving worker re-runs it.",
    icon: HeartPulse,
    accentVar: "--color-accent",
    order: 5,
  },
};

export function workflowGuide(key: string): WorkflowGuide | undefined {
  return WORKFLOW_GUIDES[key];
}

/** Guides first, in curated order; anything unrecognised keeps API order
 *  after them. */
export function compareWorkflows(a: string, b: string): number {
  const ao = WORKFLOW_GUIDES[a]?.order ?? Number.MAX_SAFE_INTEGER;
  const bo = WORKFLOW_GUIDES[b]?.order ?? Number.MAX_SAFE_INTEGER;
  return ao - bo;
}
