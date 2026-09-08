# apps/api

**Responsibility** — the FastAPI entrypoint: HTTP routers, request/response
schemas, the auth dependency (admin JWT and session-scoped candidate
tokens), and the composition root that builds every port's real adapter from
settings. It computes nothing itself — a route validates the request, calls
one port or one engine function, and returns the uniform response envelope.
`POST /session/turns` and `POST /session/finish` never wait on the workflow:
they create/find the run row, fire-and-forget `WorkflowEngine.start()` via
`deps.spawn()`, and answer `202` immediately.

**Public surface** — the ASGI app at `interviewer_api.main:app`; nothing else
is meant to be imported from outside this app.

**Depends on** — every port in `interviewer_core.ports`, built by this app's
own `deps.py` from `interviewer_core.config` settings and
`interviewer_core.registry.require_spec`.

**Invariants** — `POST /session/turns` stores the upload and enqueues a run;
it never transcribes, composes or scores inside the request. Every route
except `/auth/*`, `/i/{slug}/claim`, `/jobs`, `/jobs/{area_id}/start`,
`/healthz` and `/readyz` requires a valid bearer token, checked by one
dependency (`deps.require_admin` / `deps.require_candidate_session`), never
by convention per-route. No candidate-token route ever serialises `score`,
`verdict` or `rationale`. `POST /jobs/{area_id}/start` is a second,
no-credential entry point into the same session/token world `POST
/i/{slug}/claim` creates — it mints and self-claims a single-use, one-hour
`InterviewInvite` server-side (`routers/jobs.py`) rather than reusing
`claim()`'s code, so it never touches `session.py`.

**Where to change what** — a new route → a router module under `routers/`
plus a line in `main.py`'s `include_router` calls; a new port/repository the
app needs → a `@lru_cache` getter in `deps.py`, appended at the end of its
section, never reordered; auth rules → `deps.require_role` /
`deps.require_candidate_session`, not duplicated per router; JWT/bcrypt
mechanics → `security.py`; the envelope or error → `envelope.py` /
`errors.py`.

**Traps** — **`deps.py` is append-only during parallel waves**: two branches
restructuring it collide by construction; a new dependency is always a new
function at the end of its section. `Depends(deps.get_x)` — not calling
`deps.get_x()` directly inside a route — is what makes a dependency
override-able in tests; a route that reaches a singleton any other way is
untestable without real Postgres/Redis. Workflow steps hold a **direct
reference** to whatever `LLMPort`/pipeline they were built with at
composition time — overriding `deps.get_llm` after the engine is built does
not reach them (see `apps/api/tests/conftest.py`'s `Graph(llm=...)`
construction-time override). `InviteRepository`/`SessionRepository` (T05,
frozen) have no `list()` — `GET /invites` and `GET /admin/sessions` (plural)
are not implemented for that reason; `DELETE /invites/{id}` calls the port's
`delete()`, which is a hard remove, not a `status="retired"` update — every
externally observable behaviour (claim fails the same way, existing
sessions untouched) is identical either way.
