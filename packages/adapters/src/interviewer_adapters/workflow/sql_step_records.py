"""SQL-backed `StepRecordStore` -- the Postgres half of "Redis is transport
and lease; Postgres is the durable truth" (PRD §5.3). `redis_streams`
requires this: a worker is a separate process from the one that enqueued
the run, so an in-memory store (T07a's, still what `inline`'s tests run on)
cannot carry a checkpoint across that boundary.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlmodel import col

from interviewer_adapters.persistence.session import SessionFactory
from interviewer_adapters.persistence.tables import WorkflowStepRecordTable
from interviewer_core.domain.entities import WorkflowStepRecord


def _to_domain(row: WorkflowStepRecordTable) -> WorkflowStepRecord:
    return WorkflowStepRecord(
        run_id=row.run_id,
        name=row.name,
        status=row.status,  # type: ignore[arg-type]
        output=row.output_json,
        attempts=row.attempts,
        updated_at=row.updated_at,
    )


class SqlStepRecordStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get(self, run_id: str, name: str) -> WorkflowStepRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(WorkflowStepRecordTable).where(
                    col(WorkflowStepRecordTable.run_id) == run_id,
                    col(WorkflowStepRecordTable.name) == name,
                )
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def save(self, record: WorkflowStepRecord) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(WorkflowStepRecordTable).where(
                    col(WorkflowStepRecordTable.run_id) == record.run_id,
                    col(WorkflowStepRecordTable.name) == record.name,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = WorkflowStepRecordTable(
                    run_id=record.run_id,
                    name=record.name,
                    status=record.status,
                    output_json=dict(record.output) if record.output is not None else None,
                    attempts=record.attempts,
                    updated_at=record.updated_at,
                )
            else:
                row.status = record.status
                row.output_json = dict(record.output) if record.output is not None else None
                row.attempts = record.attempts
                row.updated_at = record.updated_at
            session.add(row)
            await session.commit()
