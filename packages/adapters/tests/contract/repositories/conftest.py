from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlmodel import SQLModel

from interviewer_adapters.persistence.repositories import (
    SqlInviteRepository,
    SqlPersonaRepository,
    SqlReportRepository,
    SqlRunRepository,
    SqlSessionRepository,
    SqlTurnRepository,
)
from interviewer_adapters.persistence.session import make_engine, make_session_factory
from interviewer_adapters.persistence.tables import (  # noqa: F401  (populate metadata)
    AreaTable,
    ArtifactTable,
    InterviewInviteTable,
    InterviewReportTable,
    PersonaTable,
    SessionTable,
    TurnTable,
    UserTable,
    WorkflowRunTable,
    WorkflowStepRecordTable,
)

from ._shared import Repos

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://interviewer:interviewer@localhost:5433/interviewer",
)


@pytest.fixture
async def sql_repos() -> AsyncIterator[Repos]:
    engine = make_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = make_session_factory(engine)
    yield Repos(
        persona=SqlPersonaRepository(factory),
        invite=SqlInviteRepository(factory),
        session=SqlSessionRepository(factory),
        turn=SqlTurnRepository(factory),
        report=SqlReportRepository(factory),
        run=SqlRunRepository(factory),
    )

    async with engine.begin() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            await conn.execute(table.delete())
    await engine.dispose()
