"""Every entity of PRD §4: frozen dataclasses, immutable updates only.

No pydantic here -- these are plain `dataclasses`, validated in
`__post_init__`, raising `DomainError`. Nothing below performs I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from interviewer_core.errors import DomainError

SessionPhase = Literal[
    "created",
    "intake",
    "questioning",
    "closing",
    "evaluating",
    "completed",
    "abandoned",
    "failed",
]

TurnKind = Literal["intake", "question", "closing"]
PersonaStatus = Literal["draft", "published", "retired"]
InviteStatus = Literal["active", "retired"]
QuestionPolicyKind = Literal["guided", "adaptive", "stress"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
StepStatus = Literal["pending", "succeeded", "failed"]


@dataclass(frozen=True)
class User:
    id: str
    email: str
    password_hash: str
    role: Literal["admin"]
    created_at: datetime


@dataclass(frozen=True)
class Area:
    id: str
    slug: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class PersonaQuestion:
    ref: str
    topic: str
    text: str
    expected_answer: str
    weight: float = 1.0
    follow_up_depth: int = 0

    def __post_init__(self) -> None:
        if not self.ref:
            raise DomainError("a persona question is missing its ref")
        if not self.text:
            raise DomainError(f"persona question {self.ref!r} is missing its text")
        if not self.expected_answer:
            raise DomainError(f"persona question {self.ref!r} is missing its expected_answer")


@dataclass(frozen=True)
class Persona:
    id: str
    area_id: str
    name: str
    version: int
    status: PersonaStatus
    language: str
    voice: str | None
    llm_provider: str
    llm_model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    greeting_text: str
    intake_prompt_text: str
    farewell_text: str
    questions: tuple[PersonaQuestion, ...]
    policy: QuestionPolicyKind
    min_coverage: float
    max_questions: int
    rubric: str
    created_at: datetime

    def __post_init__(self) -> None:
        refs = [q.ref for q in self.questions]
        duplicates = {r for r in refs if refs.count(r) > 1}
        if duplicates:
            raise DomainError(f"persona {self.id!r} has duplicate question refs: {duplicates}")
        if not self.questions:
            raise DomainError(f"persona {self.id!r} has no questions")


@dataclass(frozen=True)
class InviteClaimability:
    claimable: bool
    reason: Literal["expired", "retired", "exhausted"] | None = None


@dataclass(frozen=True)
class InterviewInvite:
    id: str
    slug: str
    persona_id: str
    passkey_hash: str
    expires_at: datetime
    max_sessions: int
    used_count: int
    status: InviteStatus
    created_at: datetime

    def is_claimable(self, now: datetime) -> InviteClaimability:
        if self.status == "retired":
            return InviteClaimability(claimable=False, reason="retired")
        if now >= self.expires_at:
            return InviteClaimability(claimable=False, reason="expired")
        if self.used_count >= self.max_sessions:
            return InviteClaimability(claimable=False, reason="exhausted")
        return InviteClaimability(claimable=True)


@dataclass(frozen=True)
class QuestionCoverage:
    asked: bool = False
    answered: bool = False
    confidence: float = 0.0


@dataclass(frozen=True)
class Session:
    id: str
    invite_id: str
    persona_id: str
    phase: SessionPhase
    candidate_name: str | None
    name_confidence: float | None
    coverage: Mapping[str, QuestionCoverage]
    started_at: datetime
    ended_at: datetime | None = None


@dataclass(frozen=True)
class Turn:
    id: str
    session_id: str
    index: int
    kind: TurnKind
    question_ref: str | None
    transcript: str | None
    audio_artifact_id: str | None
    usage: Mapping[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class Artifact:
    id: str
    session_id: str
    kind: str
    mime: str
    size_bytes: int
    uri: str
    checksum: str
    created_at: datetime


@dataclass(frozen=True)
class QuestionScore:
    question_ref: str
    score: float
    verdict: str
    rationale: str


@dataclass(frozen=True)
class InterviewReport:
    id: str
    session_id: str
    persona_id: str
    scores: tuple[QuestionScore, ...]
    overall_score: float
    summary: str
    created_at: datetime


@dataclass(frozen=True)
class WorkflowRun:
    id: str
    workflow: str
    idempotency_key: str
    status: RunStatus
    input: Mapping[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkflowStepRecord:
    run_id: str
    name: str
    status: StepStatus
    output: Mapping[str, Any] | None
    attempts: int
    updated_at: datetime
