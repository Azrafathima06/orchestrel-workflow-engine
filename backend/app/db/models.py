"""SQLAlchemy 2.x typed declarative models for the six core entities.

Status columns map directly to the enums in app.core.states via native
PostgreSQL enum types — one definition of "what states exist," reused by
both the domain layer and the schema, rather than two parallel universes
that could drift apart.

No CAS repository layer here yet (that belongs to the reconciler, M3+).
These are plain mapped columns; the compare-and-set update statements the
architecture calls for are guarded SQL the orchestration layer will issue
against these tables, e.g.:

    UPDATE task_run SET status = 'queued', ...
     WHERE id = :id AND status = 'pending'

The `(status, next_attempt_at)`, `(status, queued_at)`, and
`(status, lease_expires_at)` indexes on task_run exist specifically so
that future recovery-sweeper query can efficiently do that.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as EnumType

from app.core.states import AttemptStatus, TaskStatus, TriggerType, WorkflowStatus
from app.db.base import Base

# All persisted moments are timezone-aware; naive datetimes have no place
# in a system whose durability guarantees depend on comparing timestamps
# across processes (see docs/reliability.md: the database clock is
# authoritative).
Timestamptz = PG_TIMESTAMP(timezone=True)


def _pg_enum(enum_cls: type, name: str) -> EnumType:
    """A native PostgreSQL enum type backed by enum_cls's string values.

    values_callable ensures the DB stores 'pending', 'running', etc. (the
    StrEnum values) rather than Python's default member names.
    """
    return Enum(enum_cls, name=name, values_callable=lambda e: [member.value for member in e])


class WorkflowDefinition(Base):
    """A reusable, versioned workflow DAG definition."""

    __tablename__ = "workflow_definition"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_workflow_definition_version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamptz, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        Timestamptz, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="definition")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="definition")


class WorkflowRun(Base):
    """One concrete execution of one workflow definition."""

    __tablename__ = "workflow_run"
    __table_args__ = (
        Index("ix_workflow_run_status_created_at", "status", "created_at"),
        Index("ix_workflow_run_definition_key_created_at", "definition_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_definition.id"), nullable=False
    )
    definition_key: Mapped[str] = mapped_column(Text, nullable=False)
    spec_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        _pg_enum(WorkflowStatus, "workflow_status"),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    trigger_type: Mapped[TriggerType] = mapped_column(
        _pg_enum(TriggerType, "trigger_type"), nullable=False
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("schedule.id"), nullable=True
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        Timestamptz, nullable=False, server_default=func.now()
    )

    definition: Mapped["WorkflowDefinition"] = relationship(back_populates="runs")
    schedule: Mapped["Schedule | None"] = relationship(back_populates="runs")
    tasks: Mapped[list["TaskRun"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class TaskRun(Base):
    """Materialised execution state for exactly one DAG node in one workflow run."""

    __tablename__ = "task_run"
    __table_args__ = (
        UniqueConstraint("run_id", "task_key", name="uq_task_run_run_id_task_key"),
        Index("ix_task_run_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_task_run_status_queued_at", "status", "queued_at"),
        Index("ix_task_run_status_lease_expires_at", "status", "lease_expires_at"),
        Index("ix_task_run_run_id_status", "run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False
    )
    task_key: Mapped[str] = mapped_column(Text, nullable=False)
    handler: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        _pg_enum(TaskStatus, "task_status"), nullable=False, default=TaskStatus.PENDING
    )
    depends_on: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    dispatch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["WorkflowRun"] = relationship(back_populates="tasks")
    attempts: Mapped[list["TaskAttempt"]] = relationship(
        back_populates="task_run", cascade="all, delete-orphan"
    )


class TaskAttempt(Base):
    """Evidence of one actual execution attempt: proves retries, distinct workers, durations."""

    __tablename__ = "task_attempt"
    __table_args__ = (
        UniqueConstraint(
            "task_run_id", "attempt_number", name="uq_task_attempt_task_run_id_attempt_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        _pg_enum(AttemptStatus, "attempt_status"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(Text, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(Timestamptz, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    task_run: Mapped["TaskRun"] = relationship(back_populates="attempts")


class Schedule(Base):
    """Persisted schedule configuration. No execution logic lives here yet."""

    __tablename__ = "schedule"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_definition.id"), nullable=False
    )
    cron: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, default="UTC", server_default=text("'UTC'")
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(Timestamptz, nullable=True)
    next_fire_at: Mapped[datetime] = mapped_column(Timestamptz, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        Timestamptz, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        Timestamptz, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    definition: Mapped["WorkflowDefinition"] = relationship(back_populates="schedules")
    runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="schedule")


class ScheduleFire(Base):
    """Idempotency ledger: at most one run per (schedule, scheduled window)."""

    __tablename__ = "schedule_fire"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("schedule.id"), primary_key=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(Timestamptz, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_run.id"), nullable=False
    )
