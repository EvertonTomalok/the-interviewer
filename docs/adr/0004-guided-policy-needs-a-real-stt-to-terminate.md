# ADR 0004: `guided` needs a real STT (or LLM) to terminate; the demo's sample persona uses `adaptive`

## Status

Accepted. Documented, not fixed -- `GuidedPolicy` behaves correctly for
its actual job; the mismatch is with `STT_PROVIDER=fake` specifically.

## Context

Running `scripts/demo.py` against a fresh stack with no STT key configured
(`STT_PROVIDER=fake`, the documented, honest fallback) with a `guided`
persona and a real, prose `expected_answer` per question hung: the
interview asked question 1 forever, past `persona.max_questions`, until
`SESSION_MAX_TURNS` (an unrelated, API-level ceiling) finally cut it off
with a 409.

The cause is two behaviors composing badly, neither one wrong on its own:

- `GuidedPolicy.pick_next` only advances past a question once
  `QuestionCoverage.answered` is `True` (`engine/policies.py`).
  `answered` is set by `assess_answer` (`engine/coverage.py`), which is a
  real vocabulary-overlap check against `expected_answer` -- exactly what
  a real candidate's real STT transcript needs to be scored honestly.
- `FakeSTT.transcribe()` (T04) returns
  `f"[fake transcript {sha256(audio)[:8]}]"` -- content-free by design,
  the same way every other fake in this repo is (a scripted `FakeLLM`
  answer or a silent `FakeTTS` clip never claims to carry meaning either).
  Its vocabulary can never overlap with a real `expected_answer`, so
  `answered` never becomes `True`, and `guided` never moves on.

`completion_reason`'s other exit, `asked_so_far >= persona.max_questions`,
does not save it: `asked_so_far` counts *distinct* questions marked
`asked`, capped at `len(persona.questions)` -- with `guided` stuck asking
the same one question, that count never passes 1.

## Decision

`AdaptivePolicy` does not gate advancement on `answered` -- it moves to
the next question once a question's own `follow_up_depth` budget of
attempts is spent (`asked - 1 < follow_up_depth`), regardless of score.
With `follow_up_depth = 0` per question, that is one attempt each.

`scripts/demo.py`'s sample persona uses `policy: "adaptive"`,
`follow_up_depth: 0` on every question, and `max_questions ==
len(questions)`, so it terminates on the `max_questions` reason under
`FakeSTT` -- true to the "degrade honestly" requirement (PRD's own words
for this fallback) without silently hanging. Under a real STT and a real
answer, the same persona still terminates early on the `min_coverage`
reason whenever a genuine answer clears it, same as `guided` would.

## Consequences

- `guided` is the right default for a **real** interview (STT + LLM
  configured): it asks every question once, in order, and only repeats
  none -- exactly the PRD's description of it. It is not a safe choice
  for a persona meant to run end-to-end under `STT_PROVIDER=fake`.
- A persona authored for demo/CI purposes under `STT_PROVIDER=fake`
  should use `adaptive` with `follow_up_depth: 0` and `max_questions ==
  len(questions)`, the way `scripts/demo.py`'s does -- or supply a real
  STT/LLM pair instead.
- Not changed: `GuidedPolicy`, `assess_answer`, or `completion_reason`.
  Each is correct for what it is asked to do; the fix belongs to whichever
  persona is choosing to run on a content-free transcript.
