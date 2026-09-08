#!/usr/bin/env python3
"""`make seed` -- an admin user and three sample software-engineering
jobs, each one published area + persona, ready for `GET /jobs` the moment
the API is up.

The admin email/password come from `Settings` (`SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` in `.env`, per this package's own "no module reads
`os.environ` directly" rule) -- set them there rather than editing this
file, so a real credential never needs to touch a diff.

Idempotent: re-run any time. An area whose slug already exists, or one
that already has a published persona, is left alone and reported, not
re-created -- so a partially-seeded database from an earlier failed run
just picks up where it left off. Re-running after only the *password*
changed in `.env` does not update an already-seeded admin's password --
delete that user first if you need to rotate it.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from interviewer_api import deps
from interviewer_api.security import hash_secret
from interviewer_core.domain.entities import Area, Persona, PersonaQuestion, User

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
