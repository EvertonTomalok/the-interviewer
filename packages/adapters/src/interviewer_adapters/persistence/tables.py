"""SQLModel table classes. A table is not a domain object -- see this
package's `CONTEXT.md`. Nothing here leaves `persistence/`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _dt_column(*, nullable: bool = False) -> Column[Any]:
    return Column(DateTime(timezone=True), nullable=nullable)


class UserTable(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    role: str
    created_at: datetime = Field(sa_column=_dt_column())


class AreaTable(SQLModel, table=True):
    __tablename__ = "areas"

    id: str = Field(primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str = ""


class PersonaTable(SQLModel, table=True):
    __tablename__ = "personas"
    __table_args__ = (UniqueConstraint("area_id", "version", name="uq_personas_area_version"),)

    id: str = Field(primary_key=True)
    area_id: str = Field(index=True)
    name: str
    version: int
    status: str
    language: str
    voice: str | None = None
    llm_provider: str
    llm_model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    greeting_text: str
    intake_prompt_text: str
    farewell_text: str
    questions_json: list[dict[str, Any]] = Field(sa_column=Column(JSONB, nullable=False))
    policy: str
    min_coverage: float
    max_questions: int
    rubric: str
    created_at: datetime = Field(sa_column=_dt_column())


class InterviewInviteTable(SQLModel, table=True):
    __tablename__ = "interview_invites"

    id: str = Field(primary_key=True)
    slug: str = Field(unique=True, index=True)
    persona_id: str = Field(index=True)
    passkey_hash: str
    expires_at: datetime = Field(sa_column=_dt_column())
    max_sessions: int
    used_count: int
    status: str
    created_at: datetime = Field(sa_column=_dt_column())


class SessionTable(SQLModel, table=True):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_persona_phase", "persona_id", "phase"),
        Index("ix_sessions_started_at", "started_at"),
    )

    id: str = Field(primary_key=True)
    invite_id: str = Field(index=True)
    persona_id: str = Field(index=True)
    phase: str
    candidate_name: str | None = None
    name_confidence: float | None = None
    coverage_json: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    started_at: datetime = Field(sa_column=_dt_column())
    ended_at: datetime | None = Field(sa_column=_dt_column(nullable=True))


class TurnTable(SQLModel, table=True):
    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("session_id", "index", name="uq_turns_session_index"),)

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    index: int
    kind: str
    question_ref: str | None = None
    transcript: str | None = None
    audio_artifact_id: str | None = None
    usage_json: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(sa_column=_dt_column())


class ArtifactTable(SQLModel, table=True):
    __tablename__ = "artifacts"

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    kind: str
    mime: str
    size_bytes: int
    uri: str
    checksum: str
    created_at: datetime = Field(sa_column=_dt_column())


class InterviewReportTable(SQLModel, table=True):
    __tablename__ = "interview_reports"

    id: str = Field(primary_key=True)
    session_id: str = Field(unique=True, index=True)
    persona_id: str = Field(index=True)
    scores_json: list[dict[str, Any]] = Field(sa_column=Column(JSONB, nullable=False))
    overall_score: float
    summary: str
    created_at: datetime = Field(sa_column=_dt_column())


class WorkflowRunTable(SQLModel, table=True):
    __tablename__ = "workflow_runs"

    id: str = Field(primary_key=True)
    workflow: str
    idempotency_key: str = Field(unique=True, index=True)
    status: str
    input_json: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    error: str | None = None
    created_at: datetime = Field(sa_column=_dt_column())
    updated_at: datetime = Field(sa_column=_dt_column())


class WorkflowStepRecordTable(SQLModel, table=True):
    __tablename__ = "workflow_step_records"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_step_records_run_name"),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    name: str
    status: str
    output_json: dict[str, Any] | None = Field(sa_column=Column(JSONB, nullable=True))
    attempts: int
    updated_at: datetime = Field(sa_column=_dt_column())
