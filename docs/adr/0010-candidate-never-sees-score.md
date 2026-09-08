# ADR 0010: the candidate never sees a score

## Status

Accepted.

## Context

`InterviewReport` (overall score, per-question score/verdict/rationale) is
computed and stored the moment `evaluation_steps.py`'s workflow finishes.
Every route the candidate's session token can reach lives in
`apps/api/src/interviewer_api/routers/session.py` — whose module docstring
states, in the code itself: *"No route in this module ever serves a
score."* `finish()`'s response carries a farewell and a closing status,
nothing from `InterviewReport`.

## Decision

Scoring exists for the reviewer, not the candidate. `POST
/session/{id}/finish` ends the interview and starts the evaluation
workflow, but the candidate's own session token has no route to that
workflow's output — `GET /admin/sessions/{id}` is admin-role-gated and is
the only route that reads `InterviewReport`.

Reasons this is a boundary, not an oversight:

- **A score mid-interview would change how a candidate answers**, turning
  an interview into a test the candidate is coached by, defeating the point
  of comparing candidates against a fixed rubric.
- **A wrong or harsh automated score shown directly to a candidate is a
  support and fairness problem** this PoC has no process for — a human
  reviewer reading the transcript first is the intended safety check, not
  a UI omission waiting to be filled in.
- **The split is enforced at the route layer, where it is cheap to verify**:
  a test asserting "no `session` router response model contains a score
  field" is a permanent, mechanical check, unlike a UI convention that
  quietly stops being true.

## Consequences

- The candidate's last screen ever says is "sent for review" — text that
  is true the moment `finish` returns, before evaluation even runs, so
  there is no window where the page could leak a partial score by racing
  the workflow.
- Any future feature that shows a candidate *something* post-interview
  (a thank-you page, a status check) must be built as a genuinely new,
  audited response shape — not as a widened `GET /session/{id}` — because
  the current guarantee is "no route", not "no route yet, trust the
  frontend."
- The admin page is, in this project's own words (T10's task brief), "the
  reason the product stores anything" — this ADR is the other half of that
  sentence: it is also the *only* reason a score is ever computed at all,
  from the candidate-visible side of the system.
