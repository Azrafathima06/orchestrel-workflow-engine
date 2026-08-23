"""Celery application. Transport configuration only — no orchestration logic.

Celery's role in this system is deliberately narrow: it moves messages
between processes. It does not own DAG state, does not decide what runs
next, and does not store results. PostgreSQL does all of that.
"""

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery("workflow_engine", broker=settings.broker_url)

celery_app.conf.update(
    # ---- No result backend -------------------------------------------
    # Every outcome we care about is already persisted to task_run and
    # task_attempt. A Redis result backend would be a second, weaker copy
    # of that state with a TTL, and it roughly doubles broker traffic —
    # which matters on a free-tier broker.
    result_backend=None,
    task_ignore_result=True,
    # ---- Delivery semantics ------------------------------------------
    # acks_late: a message is acknowledged after the task finishes, not on
    # receipt, so a worker killed mid-task leaves the message to be
    # redelivered. Safe here because the runner's claim guard rejects a
    # duplicate delivery of an already-advanced attempt.
    task_acks_late=True,
    # prefetch 1: a worker reserves exactly one message at a time instead
    # of greedily buffering. Without this, one worker can grab all four
    # shards while its peers idle, and the fan-out would only *look*
    # distributed.
    worker_prefetch_multiplier=1,
    # task_reject_on_worker_lost is deliberately left OFF (the default).
    # With it enabled, a hard-killed worker's message is requeued
    # immediately by the broker. Our recovery model (M5) instead detects
    # abandoned work in PostgreSQL via lease expiry and mints a NEW attempt
    # number, which keeps the attempt history honest and prevents a
    # resurrected zombie from overwriting newer state. Letting the broker
    # also requeue the SAME attempt number would race that mechanism for
    # no benefit — the DB-driven sweeper is the single, auditable recovery
    # path.
    broker_transport_options={
        # Must exceed the longest legitimate in-flight time (including the
        # delayed retries added in M5) or Redis redelivers a message that
        # is still being worked on.
        "visibility_timeout": settings.broker_visibility_timeout,
    },
    # ---- Chatter reduction -------------------------------------------
    # Both of these generate continuous broker traffic we do not consume:
    # we derive worker activity from persisted task_attempt rows rather
    # than from Celery events or remote-control pings.
    worker_send_task_events=False,
    worker_enable_remote_control=False,
    # Celery otherwise captures stdout and re-emits it through its own
    # logger at WARNING level, which would relabel every structlog INFO
    # line as a warning. We write structured output to stdout ourselves;
    # let it through untouched.
    worker_redirect_stdouts=False,
    # ---- Serialization ------------------------------------------------
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # ---- Routing ------------------------------------------------------
    # Two queues so reconciliation is never starved behind long-running
    # task work. Both are consumed by the same worker processes locally;
    # separating them onto dedicated workers later is a flag change.
    task_default_queue="tasks",
    task_routes={
        "app.worker.tasks.execute_task": {"queue": "tasks"},
        "app.worker.tasks.reconcile": {"queue": "orchestrator"},
    },
)

celery_app.conf.beat_schedule = {
    "recovery-sweep": {
        "task": "app.worker.tasks.scheduler_tick",
        "schedule": float(settings.scheduler_tick_seconds),
        "options": {"queue": "orchestrator"},
    }
}


def _assert_timing_config_is_consistent() -> None:
    """Fail fast on a broker timeout that cannot hold our longest in-flight work.

    If `visibility_timeout` is shorter than the longest legitimate time a
    message can be outstanding, Redis redelivers work that is still running.
    Our claim guard would reject the duplicate, but the task would then sit
    un-acked and the failure mode is confusing. Better to refuse to start.
    """
    longest_in_flight = (
        settings.max_task_timeout_seconds
        + settings.lease_grace_seconds
        + settings.max_retry_countdown_seconds
    )
    if settings.broker_visibility_timeout <= longest_in_flight:
        raise ValueError(
            "broker_visibility_timeout "
            f"({settings.broker_visibility_timeout}s) must exceed the longest "
            f"possible in-flight time ({longest_in_flight}s = task timeout "
            f"{settings.max_task_timeout_seconds}s + lease grace "
            f"{settings.lease_grace_seconds}s + max retry countdown "
            f"{settings.max_retry_countdown_seconds}s)"
        )


_assert_timing_config_is_consistent()

# Import for side effects: registers the task functions with this app.
celery_app.autodiscover_tasks(["app.worker"], force=True)
