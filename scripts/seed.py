#!/usr/bin/env python3
"""`make seed` -- an admin user, three sample software-engineering jobs
(each one published area + persona, ready for `GET /jobs` the moment the
API is up), and a handful of demo `Session`/`Turn`/`InterviewReport` rows so
`/admin.html` shows a populated, realistic review queue on a fresh database
instead of an empty table.

The admin email/password come from `Settings` (`SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` in `.env`, per this package's own "no module reads
`os.environ` directly" rule) -- set them there rather than editing this
file, so a real credential never needs to touch a diff.

Idempotent: re-run any time. An area whose slug already exists, or one
that already has a published persona, is left alone and reported, not
re-created -- so a partially-seeded database from an earlier failed run
just picks up where it left off. Re-running after only the *password*
changed in `.env` does not update an already-seeded admin's password --
delete that user first if you need to rotate it. The demo sessions use
fixed ids (`demo-session-*`) for the same reason -- `sessions.get(id)`
before `add()`, never a duplicate row.

The demo sessions are written directly through the repositories, not
through `TurnPipeline`/the workflow engine -- there is no LLM or STT call
involved, so the transcripts and scores below are hand-authored, not
generated. That is a deliberate shortcut for demo data, not a pattern to
copy for anything that must behave like a real interview turn.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from typing import Any

from interviewer_api import deps
from interviewer_api.security import hash_secret
from interviewer_core.domain.entities import (
    Area,
    InterviewReport,
    Persona,
    PersonaQuestion,
    QuestionCoverage,
    QuestionScore,
    Session,
    Turn,
    User,
)

# `follow_up_depth=2` on two-plus questions per job plus `policy="adaptive"`
# is what makes the interview actually branch on what the candidate said --
# `AdaptivePolicy` (packages/core/.../engine/policies.py) re-asks a
# thin-coverage question up to its own `follow_up_depth` times before
# moving on, so these aren't just descriptive numbers.
_JOBS: list[dict[str, Any]] = [
    {
        "slug": "backend-python",
        "area_name": "Backend Engineering",
        "area_description": "Server-side services, APIs and data pipelines in Python.",
        "persona_name": "Python Software Engineer",
        "greeting_text": (
            "Hi, thanks for taking the time. I'm the interviewer for the Python "
            "Software Engineer role. This will be a short, voice conversation -- "
            "I'll ask a handful of questions about your backend experience, and "
            "I'll follow up on a couple of your answers before we wrap up."
        ),
        "intake_prompt_text": "First, could you tell me your name?",
        "farewell_text": (
            "That covers everything I needed. Thanks again for your time -- "
            "someone from the team will follow up with next steps."
        ),
        "rubric": (
            "Score each answer 0-1 on: technical correctness for the topic asked, "
            "concreteness (a real example beats a definition), and depth of "
            "follow-up reasoning when pushed. 1 is a senior-level answer with a "
            "specific example and clear tradeoffs; 0 is no relevant content."
        ),
        "questions": [
            {
                "ref": "python-fundamentals",
                "topic": "python",
                "text": (
                    "Walk me through the difference between a Python list and a "
                    "generator, and when you'd reach for one over the other."
                ),
                "expected_answer": (
                    "list stores every item in memory eagerly while a generator "
                    "yields items lazily one at a time; generators save memory for "
                    "large or infinite sequences and are used with iteration, "
                    "yield, and lazy evaluation; lists support indexing and "
                    "repeated iteration"
                ),
                "weight": 1.0,
                "follow_up_depth": 1,
            },
            {
                "ref": "concurrency",
                "topic": "concurrency",
                "text": (
                    "Tell me about a time you had to deal with concurrency or "
                    "async code in Python -- what problem were you solving?"
                ),
                "expected_answer": (
                    "describes asyncio, threading, or multiprocessing; mentions "
                    "the GIL, race condition, lock, or blocking IO; names a "
                    "concrete service or script and the specific bug or "
                    "bottleneck it fixed"
                ),
                "weight": 1.2,
                "follow_up_depth": 2,
            },
            {
                "ref": "debugging",
                "topic": "debugging",
                "text": (
                    "Describe a hard production bug you debugged. How did you "
                    "track down the root cause?"
                ),
                "expected_answer": (
                    "names a specific symptom, mentions logs, stack trace, or a "
                    "debugger, describes forming a hypothesis and testing it, and "
                    "states the actual root cause and the fix"
                ),
                "weight": 1.2,
                "follow_up_depth": 2,
            },
            {
                "ref": "testing",
                "topic": "testing",
                "text": ("How do you approach testing a new API endpoint before it ships?"),
                "expected_answer": (
                    "mentions unit tests, integration tests, pytest, mocking "
                    "external dependencies, edge cases, and validating error "
                    "responses, not just the happy path"
                ),
                "weight": 1.0,
                "follow_up_depth": 0,
            },
            {
                "ref": "system-design",
                "topic": "system-design",
                "text": (
                    "If you needed to design a service that processes a high "
                    "volume of incoming events reliably, how would you approach "
                    "it?"
                ),
                "expected_answer": (
                    "mentions a queue, idempotency, retries, backpressure, "
                    "horizontal scaling, and how to handle a failed or duplicate "
                    "event without losing or double-processing data"
                ),
                "weight": 1.3,
                "follow_up_depth": 1,
            },
            {
                "ref": "collaboration",
                "topic": "behavioral",
                "text": (
                    "Tell me about a time you disagreed with a teammate on a "
                    "technical decision. What happened?"
                ),
                "expected_answer": (
                    "describes the disagreement concretely, how they made their "
                    "case, whether they compromised or were convinced, and the "
                    "outcome for the team"
                ),
                "weight": 0.8,
                "follow_up_depth": 0,
            },
        ],
    },
    {
        "slug": "frontend-react",
        "area_name": "Frontend Engineering",
        "area_description": "Web applications in React and TypeScript.",
        "persona_name": "Frontend Software Engineer",
        "greeting_text": (
            "Hi, thanks for joining. I'm the interviewer for the Frontend "
            "Software Engineer role. I'll ask a few questions about your React "
            "and TypeScript experience and follow up where it's useful."
        ),
        "intake_prompt_text": "To start, what's your name?",
        "farewell_text": "That's everything from me -- thanks for your time today.",
        "rubric": (
            "Score each answer 0-1 on technical correctness, whether a concrete "
            "example is given, and depth under follow-up. 1 is specific and "
            "correct with real tradeoffs; 0 is no relevant content."
        ),
        "questions": [
            {
                "ref": "rerenders",
                "topic": "react",
                "text": (
                    "What causes an unnecessary re-render in a React component, "
                    "and how would you go about fixing one?"
                ),
                "expected_answer": (
                    "mentions new object or function reference on every render, "
                    "props changing identity, useMemo, useCallback, "
                    "React.memo, or state lifted too high"
                ),
                "weight": 1.0,
                "follow_up_depth": 2,
            },
            {
                "ref": "state-management",
                "topic": "state",
                "text": (
                    "How do you decide between local component state, context, "
                    "and a state management library for a given piece of state?"
                ),
                "expected_answer": (
                    "mentions scope of use, how many components need it, "
                    "update frequency, and names local state, context, or a "
                    "library like Redux or Zustand with a tradeoff"
                ),
                "weight": 1.1,
                "follow_up_depth": 1,
            },
            {
                "ref": "typescript",
                "topic": "typescript",
                "text": (
                    "Tell me about a time TypeScript's type system caught a real "
                    "bug before it shipped."
                ),
                "expected_answer": (
                    "describes a specific type error, union type, generic, or "
                    "null check that TypeScript flagged, and what the bug would "
                    "have been at runtime otherwise"
                ),
                "weight": 1.0,
                "follow_up_depth": 1,
            },
            {
                "ref": "accessibility",
                "topic": "accessibility",
                "text": "How do you make sure a new UI component is accessible?",
                "expected_answer": (
                    "mentions semantic HTML, aria attributes, keyboard "
                    "navigation, focus management, or screen reader testing"
                ),
                "weight": 0.9,
                "follow_up_depth": 0,
            },
            {
                "ref": "performance",
                "topic": "performance",
                "text": ("Describe a time you improved a slow page's load or render performance."),
                "expected_answer": (
                    "names a specific bottleneck, mentions code splitting, "
                    "lazy loading, memoization, bundle size, or a profiler, and "
                    "states the measured improvement"
                ),
                "weight": 1.1,
                "follow_up_depth": 1,
            },
            {
                "ref": "collaboration",
                "topic": "behavioral",
                "text": (
                    "Tell me about giving feedback on a teammate's pull request "
                    "that you disagreed with."
                ),
                "expected_answer": (
                    "describes the specific disagreement, how it was raised, "
                    "and the outcome or resolution"
                ),
                "weight": 0.8,
                "follow_up_depth": 0,
            },
        ],
    },
    {
        "slug": "devops-sre",
        "area_name": "DevOps / SRE",
        "area_description": "Infrastructure, deployment pipelines and production reliability.",
        "persona_name": "DevOps / SRE Engineer",
        "greeting_text": (
            "Hi, thanks for joining. I'm the interviewer for the DevOps / SRE "
            "role. I'll ask about your experience running and operating "
            "production systems, and follow up on a couple of answers."
        ),
        "intake_prompt_text": "First, what's your name?",
        "farewell_text": "That's everything I needed -- thanks for your time.",
        "rubric": (
            "Score each answer 0-1 on technical correctness, a concrete "
            "operational example, and depth under follow-up. 1 is specific "
            "and correct with real tradeoffs; 0 is no relevant content."
        ),
        "questions": [
            {
                "ref": "incident",
                "topic": "incidents",
                "text": (
                    "Walk me through the worst production incident you've been "
                    "on call for -- what happened and how did you resolve it?"
                ),
                "expected_answer": (
                    "names a specific outage or degradation, describes "
                    "detection via alert or monitoring, the root cause, "
                    "rollback or fix, and the follow-up postmortem or fix"
                ),
                "weight": 1.2,
                "follow_up_depth": 2,
            },
            {
                "ref": "ci-cd",
                "topic": "ci-cd",
                "text": (
                    "How would you design a deployment pipeline that lets a "
                    "team ship safely several times a day?"
                ),
                "expected_answer": (
                    "mentions automated tests gating the pipeline, staged "
                    "rollout or canary, feature flags, and an automated "
                    "rollback path"
                ),
                "weight": 1.1,
                "follow_up_depth": 1,
            },
            {
                "ref": "observability",
                "topic": "observability",
                "text": ("How do you decide what to monitor and alert on for a new service?"),
                "expected_answer": (
                    "mentions latency, error rate, throughput, SLOs, "
                    "dashboards, and avoiding alert fatigue with actionable "
                    "thresholds"
                ),
                "weight": 1.0,
                "follow_up_depth": 1,
            },
            {
                "ref": "infra-as-code",
                "topic": "infrastructure",
                "text": ("Tell me about your experience managing infrastructure as code."),
                "expected_answer": (
                    "names a tool such as terraform or ansible, mentions "
                    "version control, code review of infra changes, and "
                    "reproducibility"
                ),
                "weight": 1.0,
                "follow_up_depth": 0,
            },
            {
                "ref": "capacity",
                "topic": "scaling",
                "text": (
                    "Describe a time a system needed to scale to handle more "
                    "load than it was built for. What did you do?"
                ),
                "expected_answer": (
                    "names the specific bottleneck, mentions horizontal "
                    "scaling, caching, load balancing, or database sharding, "
                    "and the measured outcome"
                ),
                "weight": 1.1,
                "follow_up_depth": 1,
            },
            {
                "ref": "collaboration",
                "topic": "behavioral",
                "text": (
                    "Tell me about a time you pushed back on a deploy because "
                    "you thought it was risky."
                ),
                "expected_answer": (
                    "describes the specific risk identified, how it was "
                    "communicated to the team, and the outcome"
                ),
                "weight": 0.8,
                "follow_up_depth": 0,
            },
        ],
    },
]

# Same wording `evaluator._NOT_ANSWERED_RATIONALE` uses for a real report.
_NOT_REACHED = "the interview ended before this question was reached"

# Demo review-queue rows for `/admin.html`, written straight through the
# repositories (see the module docstring for why). `answers` is ordered --
# each entry is one question-and-answer round, in the order it was asked.
# A `phase` short of "completed" has no `scores`: the report is the last
# workflow step, and a session that never reached it has none, same as a
# real one.
_DEMO_SESSIONS: list[dict[str, Any]] = [
    {
        "id": "demo-session-backend-strong",
        "slug": "backend-python",
        "candidate_name": "Elena Fischer",
        "phase": "completed",
        "started_minutes_ago": 190,
        "answers": [
            (
                "python-fundamentals",
                "A generator yields one item at a time instead of building the "
                "whole list in memory, so I reach for it whenever I'm streaming "
                "through something large, like paginating rows out of a "
                "database -- a list only when I need to index into it or "
                "iterate it more than once.",
                0.9,
            ),
            (
                "concurrency",
                "We had a report-generation endpoint blocking the whole event "
                "loop on a slow third-party call. I moved it to asyncio with "
                "an httpx.AsyncClient and a semaphore to cap concurrent "
                "requests -- p95 latency on the rest of the API dropped back "
                "to normal immediately.",
                0.92,
            ),
            (
                "debugging",
                "A batch job was silently dropping rows. I added structured "
                "logging around the write, found the log full of a caught-and-"
                "ignored IntegrityError, traced it to a race on an upsert, and "
                "fixed it with a proper ON CONFLICT clause instead of a "
                "select-then-insert.",
                0.88,
            ),
        ],
        "scores": {
            "python-fundamentals": (
                "strong",
                0.9,
                "Correct, precise, and gives the streaming use case.",
            ),
            "concurrency": (
                "strong",
                0.92,
                "Names the real bottleneck, the fix, and the measured result.",
            ),
            "debugging": (
                "strong",
                0.88,
                "Concrete root cause and the actual fix, not just the symptom.",
            ),
            "testing": ("not_answered", 0.0, _NOT_REACHED),
            "system-design": ("not_answered", 0.0, _NOT_REACHED),
            "collaboration": ("not_answered", 0.0, _NOT_REACHED),
        },
        "summary": "Strong, specific answers on the three questions asked -- the "
        "candidate ran out of interview time before the remaining three, "
        "which count against the overall score as unanswered.",
    },
    {
        "id": "demo-session-backend-in-progress",
        "slug": "backend-python",
        "candidate_name": "Marcus Webb",
        "phase": "questioning",
        "started_minutes_ago": 12,
        "answers": [
            (
                "python-fundamentals",
                "Lists hold everything at once, generators sort of stream it "
                "I think? I'd probably use whichever one the tutorial I "
                "followed used.",
                0.35,
            ),
        ],
        "pending_question_ref": "concurrency",
        "scores": None,
    },
    {
        "id": "demo-session-frontend-weak",
        "slug": "frontend-react",
        "candidate_name": "Priya Raman",
        "phase": "completed",
        "started_minutes_ago": 420,
        "answers": [
            (
                "rerenders",
                "Usually it's just React being slow, I'd wrap it in React.memo "
                "and see if that helps.",
                0.4,
            ),
            (
                "state-management",
                "I default to Redux for basically everything, it's what I know best.",
                0.3,
            ),
        ],
        "scores": {
            "rerenders": (
                "weak",
                0.4,
                "Names React.memo but not why a re-render happened -- no mention of "
                "reference identity or props changing.",
            ),
            "state-management": (
                "weak",
                0.3,
                "No decision criteria given -- defaults to one tool regardless of scope.",
            ),
            "typescript": ("not_answered", 0.0, _NOT_REACHED),
            "accessibility": ("not_answered", 0.0, _NOT_REACHED),
            "performance": ("not_answered", 0.0, _NOT_REACHED),
            "collaboration": ("not_answered", 0.0, _NOT_REACHED),
        },
        "summary": "Both answers stay at the surface level -- no concrete example or "
        "tradeoff reasoning on either question asked.",
    },
    {
        "id": "demo-session-devops-abandoned",
        "slug": "devops-sre",
        "candidate_name": "Sam Okafor",
        "phase": "abandoned",
        "started_minutes_ago": 1440,
        "answers": [],
        "pending_question_ref": "incident",
        "scores": None,
    },
]


async def _seed_demo_session(record: dict[str, Any], personas_by_slug: dict[str, Persona]) -> None:
    sessions = deps.get_session_repo()
    turns = deps.get_turn_repo()
    reports = deps.get_report_repo()
    clock = deps.get_clock()

    if await sessions.get(record["id"]) is not None:
        print(f"seed: demo session {record['id']!r} already exists, skipping")
        return

    persona = personas_by_slug[record["slug"]]
    started_at = clock.now() - timedelta(minutes=record["started_minutes_ago"])

    coverage = {
        ref: QuestionCoverage(asked=True, answered=True, confidence=confidence)
        for ref, _answer, confidence in record["answers"]
    }
    if record.get("pending_question_ref") is not None:
        coverage[record["pending_question_ref"]] = QuestionCoverage(
            asked=True, answered=False, confidence=0.0
        )

    session = Session(
        id=record["id"],
        invite_id=f"{record['id']}-invite",
        persona_id=persona.id,
        phase=record["phase"],
        candidate_name=record["candidate_name"],
        name_confidence=0.95 if record["candidate_name"] else None,
        coverage=coverage,
        started_at=started_at,
        ended_at=(
            started_at + timedelta(minutes=18)
            if record["phase"] in ("completed", "abandoned", "failed")
            else None
        ),
    )
    await sessions.add(session)

    # `asks[i]` is the question the interviewer poses right after
    # `answers[i-1]` comes in (`asks[0]` is asked in the same round the
    # candidate gives their name -- the greeting/intake prompt itself is
    # shown before any Turn exists, per POST /i/{slug}/claim's response,
    # never stored as a row). One more entry in `asks` than in `answers`
    # means the session stopped mid-round: that last ask has no reply yet,
    # exactly the "pending" row `build_history()` looks for on a live run.
    by_ref = {q.ref: q for q in persona.questions}
    answers = record["answers"]
    asks = [ref for ref, _answer, _confidence in answers]
    pending = record.get("pending_question_ref")
    if pending is not None:
        asks.append(pending)

    turn_index = 0

    if asks or record["candidate_name"]:
        await turns.add(
            Turn(
                id=f"{record['id']}-t{turn_index}",
                session_id=session.id,
                index=turn_index,
                kind="intake",
                question_ref=None,
                transcript=f"Hi, I'm {record['candidate_name']}.",
                audio_artifact_id=None,
                usage={},
                created_at=started_at,
            )
        )
        turn_index += 1
        if asks:
            await turns.add(
                Turn(
                    id=f"{record['id']}-t{turn_index}",
                    session_id=session.id,
                    index=turn_index,
                    kind="intake",
                    question_ref=asks[0],
                    transcript=by_ref[asks[0]].text,
                    audio_artifact_id=None,
                    usage={},
                    created_at=started_at + timedelta(minutes=turn_index),
                )
            )
            turn_index += 1

    for i, (ref, answer_text, _confidence) in enumerate(answers):
        await turns.add(
            Turn(
                id=f"{record['id']}-t{turn_index}",
                session_id=session.id,
                index=turn_index,
                kind="question",
                question_ref=ref,
                transcript=answer_text,
                audio_artifact_id=None,
                usage={},
                created_at=started_at + timedelta(minutes=turn_index),
            )
        )
        turn_index += 1
        if i + 1 < len(asks):
            await turns.add(
                Turn(
                    id=f"{record['id']}-t{turn_index}",
                    session_id=session.id,
                    index=turn_index,
                    kind="question",
                    question_ref=asks[i + 1],
                    transcript=by_ref[asks[i + 1]].text,
                    audio_artifact_id=None,
                    usage={},
                    created_at=started_at + timedelta(minutes=turn_index),
                )
            )
            turn_index += 1

    if pending is None and record["phase"] == "completed" and asks:
        await turns.add(
            Turn(
                id=f"{record['id']}-t{turn_index}",
                session_id=session.id,
                index=turn_index,
                kind="closing",
                question_ref=None,
                transcript=persona.farewell_text,
                audio_artifact_id=None,
                usage={},
                created_at=started_at + timedelta(minutes=turn_index),
            )
        )
        turn_index += 1

    if record["scores"] is not None:
        scores = tuple(
            QuestionScore(question_ref=ref, score=score, verdict=verdict, rationale=rationale)
            for ref, (verdict, score, rationale) in record["scores"].items()
        )
        weights = {q.ref: q.weight for q in persona.questions}
        overall = sum(s.score * weights[s.question_ref] for s in scores) / sum(weights.values())
        await reports.add(
            InterviewReport(
                id=f"{record['id']}-report",
                session_id=session.id,
                persona_id=persona.id,
                scores=scores,
                overall_score=round(overall, 2),
                summary=record["summary"],
                created_at=session.ended_at or started_at,
            )
        )

    print(
        f"seed: demo session {record['id']!r} "
        f"({record['candidate_name']}, {record['phase']}) created"
    )


async def _seed_admin() -> None:
    users = deps.get_user_repo()
    clock = deps.get_clock()
    ids = deps.get_ids()
    settings = deps.get_settings()
    email = settings.seed_admin_email
    password = settings.seed_admin_password

    if await users.get_by_email(email) is not None:
        print(f"seed: admin {email!r} already exists, skipping")
        return

    await users.add(
        User(
            id=ids.new_id(),
            email=email,
            password_hash=hash_secret(password),
            role="admin",
            created_at=clock.now(),
        )
    )
    print(f"seed: admin user {email!r} / {password!r} -- shown once, not stored")


async def _seed_job(job: dict[str, Any]) -> None:
    areas = deps.get_area_repo()
    personas = deps.get_persona_repo()
    clock = deps.get_clock()
    ids = deps.get_ids()
    settings = deps.get_settings()

    existing = {a.slug: a for a in await areas.list()}
    area = existing.get(job["slug"])
    if area is None:
        area = Area(
            id=ids.new_id(),
            slug=job["slug"],
            name=job["area_name"],
            description=job["area_description"],
        )
        await areas.add(area)
        print(f"seed: area {job['slug']!r} created")
    else:
        print(f"seed: area {job['slug']!r} already exists, reusing")

    if await personas.latest_published(area.id) is not None:
        print(f"seed: {job['slug']!r} already has a published persona, skipping")
        return

    persona = Persona(
        id=ids.new_id(),
        area_id=area.id,
        name=job["persona_name"],
        version=1,
        status="published",
        language="en",
        voice=None,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        greeting_text=job["greeting_text"],
        intake_prompt_text=job["intake_prompt_text"],
        farewell_text=job["farewell_text"],
        questions=tuple(PersonaQuestion(**q) for q in job["questions"]),
        policy="adaptive",
        min_coverage=0.5,
        max_questions=8,
        rubric=job["rubric"],
        created_at=clock.now(),
    )
    await personas.add(persona)
    print(f"seed: published {job['persona_name']!r} under {job['slug']!r}")


async def _main() -> None:
    deps.warm_up()
    await _seed_admin()
    for job in _JOBS:
        await _seed_job(job)

    areas = deps.get_area_repo()
    personas = deps.get_persona_repo()
    existing_areas = {a.slug: a for a in await areas.list()}
    personas_by_slug: dict[str, Persona] = {}
    for job in _JOBS:
        area = existing_areas.get(job["slug"])
        persona = await personas.latest_published(area.id) if area else None
        if persona is not None:
            personas_by_slug[job["slug"]] = persona
    for record in _DEMO_SESSIONS:
        await _seed_demo_session(record, personas_by_slug)

    print("seed: done -- GET /jobs now lists every job seeded above")


def main() -> int:
    try:
        asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001 -- a seed script reports and exits, never traces
        print(f"seed: failed -- {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
