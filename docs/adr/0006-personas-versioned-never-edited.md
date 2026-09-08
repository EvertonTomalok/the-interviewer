# ADR 0006: personas are versioned, never edited in place

## Status

Accepted.

## Context

`PersonaTable` carries `(area_id, version)` as a unique constraint, and
`Persona` (the domain entity) has no `update` in `PersonaRepository` — only
`add` and `get`. A `Session` pins `persona_id` — the id of one specific
version — at claim time, not `(area_id, "latest")`.

The alternative was simpler to build: one row per area, mutated in place
whenever an admin edits the questions, the rubric, or `min_coverage`.

## Decision

A persona is immutable once created. Changing anything about an interview —
a question's wording, its `expected_answer`, `min_coverage`, the LLM model —
is authoring a new row with `version = previous + 1` and `status:
"published"`, never a `PUT`. `PersonaRepository` has no method that could
mutate one.

## Consequences

- A session started at 09:30 is scored, months later, against the exact
  `expected_answer` and rubric it was interviewed under, even if the admin
  tuned the persona at 10:00 the same day. `InterviewReport.persona_id`
  and `Session.persona_id` both point at the pinned version, not "current".
- Comparing two candidates against "the same interview" requires checking
  they share a `persona_id` — comparing across versions is comparing two
  different interviews, and the report and the transcript both make that
  version visible rather than hiding it behind an area name.
- The cost: no in-place fix for a typo in a live persona. The fix is a new
  version; invites already claimed on the old one keep running against it,
  by design, not as a bug to patch around.
- `InterviewGuide` from the original PRD sketch (§4) collapsed into
  `Persona` during T02 — one versioned row carries voice, model settings
  *and* the question/coverage rules, rather than two tables pinned
  independently. Fewer moving parts to keep in sync across a version bump.
