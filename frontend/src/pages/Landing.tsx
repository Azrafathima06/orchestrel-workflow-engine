import {
  ArrowRight,
  Database,
  Layers,
  Lock,
  Radio,
  ServerCog,
  Workflow as WorkflowIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useStatsOverview, useWorkflows } from "@/api/queries";
import { OrchestrelMark } from "@/components/OrchestrelMark";
import { formatDuration } from "@/lib/format";
import { compareWorkflows, workflowGuide } from "@/lib/workflowGuide";
import { cn } from "@/lib/utils";

const GITHUB_URL = "https://github.com/Azrafathima06/orchestrel-workflow-engine";

/** Inline GitHub mark — lucide-react dropped brand icons in v1.x. */
function GithubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

/* ------------------------------------------------------------------ hero */

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-[var(--color-border-subtle)]">
      {/* Faint DAG lattice behind the hero — the product's own subject
          matter used as texture, rather than a generic gradient. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.32]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, var(--color-border) 1px, transparent 0)",
          backgroundSize: "26px 26px",
          maskImage:
            "radial-gradient(ellipse 70% 60% at 50% 30%, black, transparent 75%)",
        }}
      />

      <div className="relative mx-auto max-w-6xl px-6 py-20 sm:py-24">
        <span className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)]/70 px-3 py-1 text-[11.5px] font-medium text-[var(--color-text-secondary)] backdrop-blur">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-[var(--color-status-succeeded)] animate-ring" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--color-status-succeeded)]" />
          </span>
          Live demo — running on real infrastructure
        </span>

        <h1 className="mt-6 max-w-3xl text-[42px] font-bold leading-[1.08] tracking-[-0.03em] text-[var(--color-text-primary)] sm:text-[54px]">
          Workflows are graphs,
          <br />
          <span className="text-[var(--color-accent)]">not scripts.</span>
        </h1>

        <p className="mt-6 max-w-2xl text-[16.5px] leading-[1.65] text-[var(--color-text-secondary)]">
          Orchestrel is a DAG-based workflow engine. It runs multi-step
          workflows across distributed workers, resolving dependencies from
          PostgreSQL, retrying failed tasks with exponential backoff, and
          containing failures so one broken task never takes down an unrelated
          branch.
        </p>

        <div className="mt-9 flex flex-wrap items-center gap-3">
          <Link
            to="/dashboard"
            className="group inline-flex h-11 items-center gap-2 rounded-[var(--radius-md)] bg-[var(--color-accent)] px-5 text-[14px] font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)]"
          >
            Open the dashboard
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
          <a
            href="#try"
            className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-1)] px-5 text-[14px] font-medium text-[var(--color-text-primary)] transition-colors hover:bg-[var(--color-surface-2)]"
          >
            Run a workflow yourself
          </a>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-md)] px-3 text-[14px] font-medium text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)]"
          >
            <GithubMark className="h-4 w-4" />
            Source
          </a>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------- live proof strip */

/**
 * Real aggregates from the API. This exists to answer the first question a
 * reviewer has about any demo — "is this actually running, or is it a
 * mockup?" — before they have to go looking.
 */
function LiveStats() {
  const stats = useStatsOverview();

  const items: { label: string; value: string }[] = stats.data
    ? [
        { label: "Workflow runs", value: String(stats.data.runs.total) },
        { label: "Tasks executed", value: String(stats.data.tasks_executed) },
        { label: "Retries performed", value: String(stats.data.retries) },
        {
          label: "Avg task duration",
          value: formatDuration(stats.data.avg_duration_ms),
        },
      ]
    : [
        { label: "Workflow runs", value: "—" },
        { label: "Tasks executed", value: "—" },
        { label: "Retries performed", value: "—" },
        { label: "Avg task duration", value: "—" },
      ];

  return (
    <section className="border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-1)]/40">
      <div className="mx-auto grid max-w-6xl grid-cols-2 gap-y-6 px-6 py-7 sm:grid-cols-4">
        {items.map((item) => (
          <div key={item.label}>
            <div className="stat-value text-[var(--color-text-primary)]">{item.value}</div>
            <div className="label-eyebrow mt-1.5">{item.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ how it works */

const STEPS = [
  {
    n: "01",
    title: "Define the graph",
    body: "A workflow is declarative JSON: tasks, the handler each one runs, and which tasks it depends on. It's validated as a real DAG — cycles, unknown and self dependencies are rejected before anything is stored.",
  },
  {
    n: "02",
    title: "Materialise into PostgreSQL",
    body: "Triggering a run writes the entire graph to the database up front. PostgreSQL — not the message broker — is the authoritative record of what exists and what state it is in.",
  },
  {
    n: "03",
    title: "Dispatch what's ready",
    body: "A task becomes runnable only once every dependency has succeeded. Independent tasks become runnable at the same moment and are dispatched to whichever workers are free.",
  },
  {
    n: "04",
    title: "Execute on distributed workers",
    body: "Workers claim a task, run its handler, and write the result back. Every attempt records the real host and process that executed it, plus its true duration.",
  },
  {
    n: "05",
    title: "Handle what goes wrong",
    body: "A retriable failure is rescheduled on a persisted exponential-backoff timer. A permanent failure skips only its own descendants. A worker that dies has its task reclaimed and re-run elsewhere.",
  },
];

function HowItWorks() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.09em] text-[var(--color-accent)]">
        How it works
      </h2>
      <p className="mt-3 max-w-2xl text-[26px] font-semibold leading-[1.25] tracking-[-0.022em] text-[var(--color-text-primary)]">
        Five stages, from a JSON definition to a finished graph.
      </p>

      <ol className="mt-11 grid grid-cols-1 gap-x-8 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">
        {STEPS.map((step) => (
          <li key={step.n} className="relative border-t border-[var(--color-border)] pt-5">
            {/* Short accent tick on the top rule — marks the start of each
                step without needing a numbered badge. */}
            <span className="absolute -top-px left-0 h-px w-10 bg-[var(--color-accent)]" />
            <div className="font-mono text-[11.5px] font-medium text-[var(--color-accent)]">
              {step.n}
            </div>
            <h3 className="mt-2 text-[15.5px] font-semibold tracking-[-0.01em] text-[var(--color-text-primary)]">
              {step.title}
            </h3>
            <p className="mt-2 text-[13.5px] leading-[1.62] text-[var(--color-text-secondary)]">
              {step.body}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* -------------------------------------------------------------- try a demo */

function TryIt() {
  const { data } = useWorkflows();

  return (
    <section
      id="try"
      className="scroll-mt-4 border-y border-[var(--color-border-subtle)] bg-[var(--color-surface-1)]/40"
    >
      <div className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.09em] text-[var(--color-accent)]">
          Try it
        </h2>
        <p className="mt-3 max-w-2xl text-[26px] font-semibold leading-[1.25] tracking-[-0.022em] text-[var(--color-text-primary)]">
          Five workflows, each built to prove one engine behaviour.
        </p>
        <p className="mt-3 max-w-2xl text-[14px] leading-[1.6] text-[var(--color-text-secondary)]">
          Open one, press <span className="text-[var(--color-text-primary)]">Run workflow</span>,
          and watch its graph execute live — nodes change colour as real
          handlers run on real workers. Start with Failure isolation or
          Parallel execution; they are the most interesting to watch.
        </p>

        <div className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...(data ?? [])]
            .sort((a, b) => compareWorkflows(a.key, b.key))
            .map((wf) => {
            const guide = workflowGuide(wf.key);
            const Icon = guide?.icon ?? WorkflowIcon;
            const accent = guide?.accentVar ?? "--color-accent";

            return (
              <Link
                key={wf.key}
                to={`/workflows/${wf.key}`}
                className="panel group flex flex-col p-5 transition-[transform,border-color] duration-150 hover:-translate-y-0.5 hover:border-[var(--color-border)]"
              >
                <div className="flex items-center gap-3">
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
                    style={{
                      backgroundColor: `color-mix(in oklab, var(${accent}) 16%, transparent)`,
                    }}
                  >
                    <Icon
                      className="h-4 w-4"
                      style={{ color: `var(${accent})` }}
                      strokeWidth={2}
                    />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-semibold text-[var(--color-text-primary)]">
                      {guide?.headline ?? wf.name}
                    </div>
                    <div className="truncate font-mono text-[11px] text-[var(--color-text-tertiary)]">
                      {wf.key}
                    </div>
                  </div>
                </div>

                <p className="mt-3.5 flex-1 text-[13px] leading-[1.6] text-[var(--color-text-secondary)]">
                  {guide?.blurb ?? wf.description}
                </p>

                <div className="mt-4 flex items-center justify-between border-t border-[var(--color-border-subtle)] pt-3">
                  <span className="font-mono text-[11px] text-[var(--color-text-tertiary)]">
                    {wf.task_count} tasks
                  </span>
                  {wf.is_public ? (
                    <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[var(--color-accent)]">
                      Open
                      <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[11.5px] text-[var(--color-text-tertiary)]">
                      <Lock className="h-3 w-3" />
                      Local only
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- architecture */

const PIECES = [
  {
    icon: Layers,
    title: "Control plane",
    body: "A FastAPI service accepts workflow triggers, materialises the DAG, and serves every read the dashboard performs.",
  },
  {
    icon: Database,
    title: "PostgreSQL — authoritative state",
    body: "Runs, tasks, dependencies and every individual attempt live here. All scheduling decisions are made by querying it.",
  },
  {
    icon: Radio,
    title: "Redis — transport only",
    body: "Celery moves messages over Redis. It holds no workflow state and no result backend, so losing it loses no work.",
  },
  {
    icon: ServerCog,
    title: "Celery workers",
    body: "Task execution never happens inside the API. Workers claim work, execute handlers, and record real host and duration.",
  },
];

function Architecture() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.09em] text-[var(--color-accent)]">
        Architecture
      </h2>
      <p className="mt-3 max-w-2xl text-[26px] font-semibold leading-[1.25] tracking-[-0.022em] text-[var(--color-text-primary)]">
        The database decides what runs next — not the queue.
      </p>
      <p className="mt-3 max-w-2xl text-[14px] leading-[1.6] text-[var(--color-text-secondary)]">
        Celery is transport and execution; it does not own DAG order. A
        purpose-built planner and reconciler resolve dependencies and apply
        every state transition against PostgreSQL, which is what makes the
        engine recoverable when a worker or the broker disappears.
      </p>

      <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {PIECES.map((piece) => (
          <div key={piece.title} className="panel flex gap-4 p-5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-accent-subtle)]">
              <piece.icon className="h-4 w-4 text-[var(--color-accent)]" strokeWidth={2} />
            </span>
            <div>
              <h3 className="text-[14.5px] font-semibold text-[var(--color-text-primary)]">
                {piece.title}
              </h3>
              <p className="mt-1.5 text-[13px] leading-[1.6] text-[var(--color-text-secondary)]">
                {piece.body}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- footer */

const STACK = [
  "Python 3.12",
  "FastAPI",
  "Celery",
  "Redis",
  "PostgreSQL 16",
  "SQLAlchemy 2",
  "Alembic",
  "React 19",
  "TypeScript",
  "Tailwind CSS",
  "Docker",
];

function Footer() {
  return (
    <footer className="border-t border-[var(--color-border-subtle)]">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <div className="flex flex-wrap gap-2">
          {STACK.map((tech) => (
            <span
              key={tech}
              className="rounded-[var(--radius-sm)] border border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] px-2.5 py-1 font-mono text-[11.5px] text-[var(--color-text-secondary)]"
            >
              {tech}
            </span>
          ))}
        </div>

        <div className="mt-9 flex flex-wrap items-center justify-between gap-4 border-t border-[var(--color-border-subtle)] pt-7">
          <div className="flex items-center gap-2.5">
            <OrchestrelMark />
            <span className="text-[14px] font-semibold text-[var(--color-text-primary)]">
              Orchestrel
            </span>
          </div>
          <div className="flex items-center gap-5 text-[13px]">
            <Link
              to="/dashboard"
              className="text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
            >
              Dashboard
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
            >
              <GithubMark className="h-3.5 w-3.5" />
              GitHub
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ page */

/** Minimal top bar — the landing page deliberately does not render the
 *  dashboard's sidebar, so a first-time visitor sees one clear next step
 *  instead of a navigation tree for a product they haven't met yet. */
function LandingNav() {
  return (
    <header className="sticky top-0 z-20 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-0)]/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-2.5">
          <OrchestrelMark />
          <span className="text-[15px] font-semibold tracking-[-0.01em] text-[var(--color-text-primary)]">
            Orchestrel
          </span>
        </div>
        <Link
          to="/dashboard"
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-md)]",
            "border border-[var(--color-border)] bg-[var(--color-surface-1)] px-3",
            "text-[13px] font-medium text-[var(--color-text-primary)]",
            "transition-colors hover:bg-[var(--color-surface-2)]",
          )}
        >
          Dashboard
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </header>
  );
}

export function Landing() {
  return (
    <div className="min-h-screen">
      <LandingNav />
      <Hero />
      <LiveStats />
      <HowItWorks />
      <TryIt />
      <Architecture />
      <Footer />
    </div>
  );
}
