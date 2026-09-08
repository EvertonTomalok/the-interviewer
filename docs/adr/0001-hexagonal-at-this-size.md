# 0001 — Hexagonal at this size

## Context

This is a modular monolith with five external concerns (LLM, speech,
storage, persistence, workflow) and one process that will eventually run as
two (API + worker). It is small enough that a simpler layout — one Django-ish
app, models with `save()`, provider calls inline in a view — would ship
faster on day one.

## Decision

Ports & Adapters anyway, enforced by an AST test on `packages/core`, not by
convention. Every external concern is a `typing.Protocol` with at least a
real adapter and a fake; the engine and the domain import none of them.

## Consequences

- Every provider swap (`LLM_PROVIDER`, `WORKFLOW_PROVIDER`,
  `STORAGE_PROVIDER`, `REPLY_MODE`) is a config flip verified by a drill, not
  a refactor.
- The whole unit suite runs with no network and no containers, because the
  fakes are the thing under test as much as the engine is.
- The up-front cost is real: a Protocol per concern, two implementations
  minimum, a registry instead of an `if/elif`. It shows up in the task list
  as the whole of wave 0 before any feature ships.
- The boundary is enforced by a test that names the offending import, so the
  cost is paid once and then defended automatically — a reviewer does not
  re-litigate it on every PR.

## What would make us reverse it

If this service stayed a single-provider, single-deployment tool with no
credible plan to swap Redis for Temporal or to add a second LLM vendor, the
port layer would be paying for optionality nobody uses. That is not this
project's bet — the PRD names the Temporal swap as the reason the workflow
port exists at all — but it is the condition under which this decision should
be revisited.
